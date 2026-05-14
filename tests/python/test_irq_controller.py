from __future__ import annotations

from device_model.mmio_base import IRQController, recv_exact

from platform_test_utils import make_socketpair


REQUIREMENTS = (
    'IRQ-001',
    'IRQ-002',
    'IRQ-005',
    'IRQ-009',
    'IRQ-010',
)


def test_set_irq_returns_false_when_channel_is_not_connected() -> None:
    controller = IRQController()

    assert controller.set_irq(3, 1) is False


def test_set_irq_sends_assert_and_deassert_frames() -> None:
    controller_sock, peer_sock = make_socketpair()
    controller = IRQController()
    controller._on_connect(controller_sock)

    assert controller.set_irq(7, 1) is True
    assert recv_exact(peer_sock, 3) == bytes([ord('I'), 7, 1])

    assert controller.set_irq(7, 0) is True
    assert recv_exact(peer_sock, 3) == bytes([ord('I'), 7, 0])

    controller._on_disconnect()
    controller_sock.close()
    peer_sock.close()


def test_pulse_irq_is_represented_as_assert_then_deassert() -> None:
    controller_sock, peer_sock = make_socketpair()
    controller = IRQController()
    controller._on_connect(controller_sock)

    assert controller.set_irq(2, 1) is True
    assert controller.set_irq(2, 0) is True

    assert recv_exact(peer_sock, 6) == bytes([ord('I'), 2, 1, ord('I'), 2, 0])

    controller._on_disconnect()
    controller_sock.close()
    peer_sock.close()