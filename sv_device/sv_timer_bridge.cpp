#include <arpa/inet.h>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <unistd.h>

#include "Vsv_timer_apb.h"
#include "verilated.h"

namespace {

constexpr uint16_t kDefaultRwPort = 7906;
constexpr uint16_t kDefaultIrqPort = 7907;
constexpr uint32_t kRegCtrl = 0x00;

bool read_exact(int fd, void *buf, size_t len)
{
    auto *ptr = static_cast<uint8_t *>(buf);
    size_t done = 0;
    while (done < len) {
        ssize_t n = ::recv(fd, ptr + done, len - done, 0);
        if (n == 0) {
            return false;
        }
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            std::perror("recv");
            return false;
        }
        done += static_cast<size_t>(n);
    }
    return true;
}

bool write_all(int fd, const void *buf, size_t len)
{
    const auto *ptr = static_cast<const uint8_t *>(buf);
    size_t done = 0;
    while (done < len) {
        ssize_t n = ::send(fd, ptr + done, len - done, MSG_NOSIGNAL);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            std::perror("send");
            return false;
        }
        done += static_cast<size_t>(n);
    }
    return true;
}

uint32_t load_le32(const uint8_t *buf)
{
    return (static_cast<uint32_t>(buf[0]) << 0)
         | (static_cast<uint32_t>(buf[1]) << 8)
         | (static_cast<uint32_t>(buf[2]) << 16)
         | (static_cast<uint32_t>(buf[3]) << 24);
}

void store_le32(uint8_t *buf, uint32_t value)
{
    buf[0] = static_cast<uint8_t>(value >> 0);
    buf[1] = static_cast<uint8_t>(value >> 8);
    buf[2] = static_cast<uint8_t>(value >> 16);
    buf[3] = static_cast<uint8_t>(value >> 24);
}

int listen_on(uint16_t port)
{
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        std::perror("socket");
        std::exit(1);
    }

    int yes = 1;
    ::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = htons(port);

    if (::bind(fd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0) {
        std::perror("bind");
        std::exit(1);
    }
    if (::listen(fd, 4) < 0) {
        std::perror("listen");
        std::exit(1);
    }
    std::printf("[SV-TIMER] Listening on 127.0.0.1:%u\n", port);
    std::fflush(stdout);
    return fd;
}

int accept_one(int listen_fd, const char *name)
{
    sockaddr_in peer{};
    socklen_t len = sizeof(peer);
    int fd = ::accept(listen_fd, reinterpret_cast<sockaddr *>(&peer), &len);
    if (fd < 0) {
        std::perror("accept");
        std::exit(1);
    }
    std::printf("[SV-TIMER] %s connected\n", name);
    std::fflush(stdout);
    return fd;
}

class SvTimerBridge {
public:
    SvTimerBridge()
        : context_(std::make_unique<VerilatedContext>()),
          dut_(std::make_unique<Vsv_timer_apb>(context_.get(), "sv_timer_apb"))
    {
        dut_->clk = 0;
        dut_->rst_n = 0;
        dut_->psel = 0;
        dut_->penable = 0;
        dut_->pwrite = 0;
        dut_->paddr = 0;
        dut_->pwdata = 0;
        eval_cycle();
        eval_cycle();
        dut_->rst_n = 1;
        eval_cycle();
    }

    uint32_t apb_read(uint32_t offset)
    {
        dut_->paddr = offset & 0xfffU;
        dut_->pwrite = 0;
        dut_->psel = 1;
        dut_->penable = 0;
        eval_half();
        dut_->penable = 1;
        eval_cycle();
        uint32_t value = dut_->prdata;
        dut_->psel = 0;
        dut_->penable = 0;
        eval_half();
        return value;
    }

    void apb_write(uint32_t offset, uint32_t value)
    {
        dut_->paddr = offset & 0xfffU;
        dut_->pwdata = value;
        dut_->pwrite = 1;
        dut_->psel = 1;
        dut_->penable = 0;
        eval_half();
        dut_->penable = 1;
        eval_cycle();
        dut_->psel = 0;
        dut_->penable = 0;
        dut_->pwrite = 0;
        eval_half();
    }

    void run_cycles(uint32_t cycles)
    {
        for (uint32_t i = 0; i < cycles; ++i) {
            eval_cycle();
        }
    }

    bool irq() const
    {
        return dut_->irq_o;
    }

private:
    void eval_half()
    {
        dut_->eval();
        context_->timeInc(1);
    }

    void eval_cycle()
    {
        dut_->clk = 0;
        eval_half();
        dut_->clk = 1;
        eval_half();
        dut_->clk = 0;
        eval_half();
    }

    std::unique_ptr<VerilatedContext> context_;
    std::unique_ptr<Vsv_timer_apb> dut_;
};

void send_irq(int irq_fd, bool level)
{
    uint8_t msg[3] = {'I', 0, static_cast<uint8_t>(level ? 1 : 0)};
    if (write_all(irq_fd, msg, sizeof(msg))) {
        std::printf("[SV-TIMER] IRQ %s\n", level ? "assert" : "deassert");
        std::fflush(stdout);
    }
}

void usage(const char *argv0)
{
    std::fprintf(stderr, "Usage: %s [--rw-port PORT] [--irq-port PORT]\n", argv0);
}

} // namespace

int main(int argc, char **argv)
{
    uint16_t rw_port = kDefaultRwPort;
    uint16_t irq_port = kDefaultIrqPort;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--rw-port" && i + 1 < argc) {
            rw_port = static_cast<uint16_t>(std::strtoul(argv[++i], nullptr, 0));
        } else if (arg == "--irq-port" && i + 1 < argc) {
            irq_port = static_cast<uint16_t>(std::strtoul(argv[++i], nullptr, 0));
        } else {
            usage(argv[0]);
            return 2;
        }
    }

    Verilated::commandArgs(argc, argv);
    SvTimerBridge bridge;

    int rw_listen = listen_on(rw_port);
    int irq_listen = listen_on(irq_port);
    int rw_fd = accept_one(rw_listen, "RW channel");
    int irq_fd = accept_one(irq_listen, "IRQ channel");

    bool last_irq = false;
    while (true) {
        uint8_t op = 0;
        if (!read_exact(rw_fd, &op, 1)) {
            break;
        }

        uint8_t hdr[6] = {};
        if (!read_exact(rw_fd, hdr, sizeof(hdr))) {
            break;
        }
        uint32_t offset = load_le32(hdr + 1);
        uint8_t size = hdr[5];

        if (op == 'R') {
            uint32_t value = bridge.apb_read(offset);
            uint8_t out[4] = {};
            store_le32(out, value);
            if (!write_all(rw_fd, out, size <= 4 ? size : 4)) {
                break;
            }
        } else if (op == 'W') {
            uint8_t payload[4] = {};
            if (size > sizeof(payload) || !read_exact(rw_fd, payload, size)) {
                break;
            }
            uint32_t value = load_le32(payload);
            bridge.apb_write(offset, value);

            if (offset == kRegCtrl && (value & 0x1U)) {
                uint32_t load = bridge.apb_read(0x04);
                bridge.run_cycles(load + 2U);
            } else {
                bridge.run_cycles(1);
            }

            bool irq_now = bridge.irq();
            if (irq_now != last_irq) {
                send_irq(irq_fd, irq_now);
                last_irq = irq_now;
            }

            uint8_t resp[8] = {};
            if (!write_all(rw_fd, resp, sizeof(resp))) {
                break;
            }

            irq_now = bridge.irq();
            if (irq_now != last_irq) {
                send_irq(irq_fd, irq_now);
                last_irq = irq_now;
            }
        } else {
            std::fprintf(stderr, "[SV-TIMER] Unknown op 0x%02x\n", op);
            break;
        }
    }

    std::printf("[SV-TIMER] disconnected\n");
    ::close(rw_fd);
    ::close(irq_fd);
    ::close(rw_listen);
    ::close(irq_listen);
    return 0;
}