#include <arpa/inet.h>
#include <cerrno>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <poll.h>
#include <string>
#include <unistd.h>

#include "Vsv_device_top.h"
#include "verilated.h"
#include "verilated_vcd_c.h"

namespace {

constexpr uint16_t kDefaultRwPort = 7906;
constexpr uint16_t kDefaultIrqPort = 7907;
constexpr uint16_t kDefaultMemPort = 7912;
constexpr uint8_t kSvDmaMasterId = 0x20;
constexpr uint32_t kIdleCyclesPerPoll = 16;
constexpr uint64_t kTraceFlushPeriod = 4096;
constexpr const char *kDefaultWaveFile = "build/sv_host_shell.vcd";

volatile std::sig_atomic_t g_stop_requested = 0;
int g_fabric_fd = -1;

void request_stop(int)
{
    g_stop_requested = 1;
}

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
                if (g_stop_requested) {
                    return false;
                }
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
                if (g_stop_requested) {
                    return false;
                }
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

void store_le64(uint8_t *buf, uint64_t value)
{
    for (int i = 0; i < 8; ++i) {
        buf[i] = static_cast<uint8_t>(value >> (8 * i));
    }
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
    std::printf("[SV-HOST] Listening on 127.0.0.1:%u\n", port);
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
    std::printf("[SV-HOST] %s connected\n", name);
    std::fflush(stdout);
    return fd;
}

class SvPeriphBridge {
public:
    explicit SvPeriphBridge(const std::string &wave_file)
        : context_(std::make_unique<VerilatedContext>()),
          dut_(std::make_unique<Vsv_device_top>(context_.get(), "sv_device_top"))
    {
        if (!wave_file.empty()) {
            Verilated::traceEverOn(true);
            trace_ = std::make_unique<VerilatedVcdC>();
            dut_->trace(trace_.get(), 99);
            trace_->open(wave_file.c_str());
            std::printf("[SV-HOST] Wave dump: %s\n", wave_file.c_str());
            std::fflush(stdout);
        }

        dut_->clk = 0;
        dut_->rst_n = 0;
        dut_->host_req_valid = 0;
        dut_->host_req_write = 0;
        dut_->host_req_addr = 0;
        dut_->host_req_size = 2;
        dut_->host_req_wdata = 0;
        eval_cycle(false);
        eval_cycle(false);
        dut_->rst_n = 1;
        eval_cycle(false);
    }

    ~SvPeriphBridge()
    {
        if (trace_) {
            trace_->flush();
            trace_->close();
        }
    }

    uint32_t apb_read(uint32_t offset)
    {
        uint32_t value = 0;
        bool error = false;
        host_apb_access(false, offset, 0, &value, &error);
        return value;
    }

    void apb_write(uint32_t offset, uint32_t value)
    {
        bool error = false;
        host_apb_access(true, offset, value, nullptr, &error);
    }

    void run_cycles(uint32_t cycles)
    {
        for (uint32_t i = 0; i < cycles; ++i) {
            eval_cycle(false);
        }
    }

    bool irq() const
    {
        return dut_->irq_o;
    }

private:
    void host_apb_access(bool write, uint32_t offset, uint32_t wdata,
                         uint32_t *rdata, bool *error)
    {
        while (!dut_->host_req_ready && !g_stop_requested) {
            eval_cycle(false);
        }

        dut_->host_req_valid = 1;
        dut_->host_req_write = write ? 1 : 0;
        dut_->host_req_addr = offset & 0xfffU;
        dut_->host_req_size = 2;
        dut_->host_req_wdata = wdata;
        eval_cycle(false);
        dut_->host_req_valid = 0;

        while (!dut_->host_rsp_valid && !g_stop_requested) {
            eval_cycle(false);
        }

        if (rdata) {
            *rdata = dut_->host_rsp_rdata;
        }
        if (error) {
            *error = dut_->host_rsp_error != 0;
        }
    }

    void eval_half()
    {
        dut_->eval();
        if (trace_) {
            trace_->dump(context_->time());
            trace_dump_count_++;
            if ((trace_dump_count_ % kTraceFlushPeriod) == 0) {
                trace_->flush();
            }
        }
        context_->timeInc(1);
    }

    void eval_cycle(bool service_ahb)
    {
        (void)service_ahb;
        dut_->clk = 0;
        eval_half();
        dut_->clk = 1;
        eval_half();
        dut_->clk = 0;
        eval_half();
    }

    std::unique_ptr<VerilatedContext> context_;
    std::unique_ptr<Vsv_device_top> dut_;
    std::unique_ptr<VerilatedVcdC> trace_;
    uint64_t trace_dump_count_ = 0;
};

void send_irq(int irq_fd, bool level)
{
    uint8_t msg[3] = {'I', 0, static_cast<uint8_t>(level ? 1 : 0)};
    if (write_all(irq_fd, msg, sizeof(msg))) {
        std::printf("[SV-HOST] IRQ %s\n", level ? "assert" : "deassert");
        std::fflush(stdout);
    }
}

void usage(const char *argv0)
{
    std::fprintf(stderr,
                 "Usage: %s [--rw-port PORT] [--irq-port PORT] [--mem-port PORT] "
                 "[--wave-file PATH] [--no-wave]\n",
                 argv0);
}

} // namespace

extern "C" uint64_t sv_fabric_read32(uint32_t addr)
{
    uint8_t hdr[16] = {};
    hdr[0] = 'F';
    hdr[1] = 'R';
    hdr[2] = kSvDmaMasterId;
    hdr[3] = 0;
    store_le64(hdr + 4, addr);
    store_le32(hdr + 12, 4);
    if (!write_all(g_fabric_fd, hdr, sizeof(hdr))) {
        std::printf("[SV-DMA] FABRIC READ  addr=0x%08x data=0x00000000 ERR\n", addr);
        std::fflush(stdout);
        return 1ULL << 32;
    }

    uint8_t status = 0xff;
    if (!read_exact(g_fabric_fd, &status, sizeof(status)) || status != 0) {
        std::printf("[SV-DMA] FABRIC READ  addr=0x%08x data=0x00000000 ERR\n", addr);
        std::fflush(stdout);
        return 1ULL << 32;
    }

    uint8_t data[4] = {};
    if (!read_exact(g_fabric_fd, data, sizeof(data))) {
        std::printf("[SV-DMA] FABRIC READ  addr=0x%08x data=0x00000000 ERR\n", addr);
        std::fflush(stdout);
        return 1ULL << 32;
    }

    uint32_t value = load_le32(data);
    std::printf("[SV-DMA] FABRIC READ  addr=0x%08x data=0x%08x OK\n", addr, value);
    std::fflush(stdout);
    return value;
}

extern "C" int sv_fabric_write32(uint32_t addr, uint32_t value)
{
    uint8_t pkt[20] = {};
    pkt[0] = 'F';
    pkt[1] = 'W';
    pkt[2] = kSvDmaMasterId;
    pkt[3] = 0;
    store_le64(pkt + 4, addr);
    store_le32(pkt + 12, 4);
    store_le32(pkt + 16, value);
    bool ok = false;
    if (write_all(g_fabric_fd, pkt, sizeof(pkt))) {
        uint8_t ack = 0xff;
        ok = read_exact(g_fabric_fd, &ack, sizeof(ack)) && ack == 0;
    }
    std::printf("[SV-DMA] FABRIC WRITE addr=0x%08x data=0x%08x %s\n",
                addr, value, ok ? "OK" : "ERR");
    std::fflush(stdout);
    return ok ? 1 : 0;
}

int main(int argc, char **argv)
{
    uint16_t rw_port = kDefaultRwPort;
    uint16_t irq_port = kDefaultIrqPort;
    uint16_t mem_port = kDefaultMemPort;
    std::string wave_file = kDefaultWaveFile;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--rw-port" && i + 1 < argc) {
            rw_port = static_cast<uint16_t>(std::strtoul(argv[++i], nullptr, 0));
        } else if (arg == "--irq-port" && i + 1 < argc) {
            irq_port = static_cast<uint16_t>(std::strtoul(argv[++i], nullptr, 0));
        } else if (arg == "--mem-port" && i + 1 < argc) {
            mem_port = static_cast<uint16_t>(std::strtoul(argv[++i], nullptr, 0));
        } else if (arg == "--wave-file" && i + 1 < argc) {
            wave_file = argv[++i];
        } else if (arg == "--no-wave") {
            wave_file.clear();
        } else {
            usage(argv[0]);
            return 2;
        }
    }

    Verilated::commandArgs(argc, argv);
    std::signal(SIGINT, request_stop);
    std::signal(SIGTERM, request_stop);

    int rw_listen = listen_on(rw_port);
    int irq_listen = listen_on(irq_port);
    int mem_listen = listen_on(mem_port);
    int rw_fd = accept_one(rw_listen, "RW channel");
    int irq_fd = accept_one(irq_listen, "IRQ channel");
    int mem_fd = accept_one(mem_listen, "fabric channel");
    g_fabric_fd = mem_fd;

    SvPeriphBridge bridge(wave_file);
    bool last_irq = bridge.irq();
    if (last_irq) {
        send_irq(irq_fd, true);
    }

    while (!g_stop_requested) {
        pollfd pfd{};
        pfd.fd = rw_fd;
        pfd.events = POLLIN;
        int ret = ::poll(&pfd, 1, 1);
        if (ret < 0) {
            if (errno == EINTR) {
                if (g_stop_requested) {
                    break;
                }
                continue;
            }
            std::perror("poll");
            break;
        }

        if (ret == 0) {
            bridge.run_cycles(kIdleCyclesPerPoll);
        } else if ((pfd.revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
            break;
        } else if ((pfd.revents & POLLIN) != 0) {
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
                bridge.run_cycles(kIdleCyclesPerPoll);
            } else if (op == 'W') {
                uint8_t payload[4] = {};
                if (size > sizeof(payload) || !read_exact(rw_fd, payload, size)) {
                    break;
                }
                uint32_t value = load_le32(payload);
                bridge.apb_write(offset, value);

                uint8_t resp[8] = {};
                if (!write_all(rw_fd, resp, sizeof(resp))) {
                    break;
                }
                bridge.run_cycles(kIdleCyclesPerPoll);

            } else {
                std::fprintf(stderr, "[SV-HOST] Unknown op 0x%02x\n", op);
                break;
            }
        }

        bool irq_now = bridge.irq();
        if (irq_now != last_irq) {
            send_irq(irq_fd, irq_now);
            last_irq = irq_now;
        }
    }

    std::printf("[SV-HOST] disconnected\n");
    ::close(rw_fd);
    ::close(irq_fd);
    ::close(mem_fd);
    ::close(rw_listen);
    ::close(irq_listen);
    ::close(mem_listen);
    return 0;
}
