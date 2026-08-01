# gotcha_gatt.py -- the Gotcha GATT server service (plan §5.2, §5.7).
#
# A lvgl-free GATT service registered alongside the contact-exchange + setup
# services in ContactExchange._ensure_services() (NimBLE accepts
# gatts_register_services only once per power-on, DESIGN.md §10). It carries the
# four Gotcha characteristics; Phase 3a wires ONLY `REVEAL` -- a WRITE the hunter
# sends to make the target flash gold (§5.7). `ATTACK`/`DUEL`/`SPOILS` are
# registered now so the handle layout is fixed for Phase 3b (the duel):
# re-registering later is impossible and would shift every handle.
#
# The responder is built with NO lvgl and NO Activity dependency, and effects are
# delivered through an injected callback (on_reveal), so Phase 4 can construct the
# same object from beacon_service.py (background participation, §5.6) and drive
# it with buzzer/LED only.
#
# IRQ routing: BLEProximity owns the radio + the single IRQ while a game is live.
# Its _irq() forwards non-scan events here via the dispatch hook set in
# set_gatt_dispatch(). This object never installs its own IRQ.
#
# NOT host-tested (the GATT radio calls are MicroPython-only, same convention as
# contact_exchange.py's radio wrapper); the pure logic it relies on
# (parse_reveal_payload / validate_reveal) is covered in tests/test_gotcha.py.

# Custom 128-bit UUIDs (Nordic-UART-derived base, plan §5.2).
GOTCHA_SVC = "6e400030-b5a3-f393-e0a9-e50e24dcca9e"
ATTACK_CHR = "6e400031-b5a3-f393-e0a9-e50e24dcca9e"
DUEL_CHR = "6e400032-b5a3-f393-e0a9-e50e24dcca9e"
SPOILS_CHR = "6e400033-b5a3-f393-e0a9-e50e24dcca9e"
REVEAL_CHR = "6e400034-b5a3-f393-e0a9-e50e24dcca9e"

# Characteristic order MUST match this list (registration order -> bind_handles).
GOTCHA_CHR_ORDER = ("attack", "duel", "spoils", "reveal")


class GotchaService(object):
    """The Gotcha GATT server: registers GOTCHA_SVC, answers inbound REVEAL writes.

    Phase 3a: only `reveal` has a handler. `attack`/`duel`/`spoils` are registered
    (handle layout fixed for the duel) but unanswered until Phase 3b."""

    def __init__(self, on_reveal=None, on_attack=None):
        # on_reveal(parsed_payload) fires on the owner's tick (drain_reveals) for a
        # valid inbound REVEAL -- it triggers the gold flash / chirp / SPOTTED.
        # on_attack(parsed_payload, conn_handle) fires (drain_attacks) for an
        # inbound ATTACK -- it starts the §5.3 duel (Phase 3b).
        self.on_reveal = on_reveal
        self.on_attack = on_attack
        self._ble = None
        self._h = {}                 # name -> value handle
        self._central = None         # conn_handle while a central is connected (§5.5)
        self._pending = []           # parsed REVEAL payloads queued from the IRQ
        self._pending_attacks = []   # (parsed, conn) ATTACK writes queued from the IRQ
        # Diagnostics (read by the controller's duel log): count IRQ events so a
        # silent responder can be traced to "IRQ never fired" vs "parse dropped it".
        self.dbg_central = 0
        self.dbg_write = 0
        self.dbg_write_h = 0         # last written value handle seen

    # ---- registration hooks (mirror ble_setup.SetupService) ----------------
    def service_tuple(self, bluetooth):
        """The (uuid, characteristics) tuple for gatts_register_services. The
        characteristic order MUST match GOTCHA_CHR_ORDER."""
        F_READ = getattr(bluetooth, "FLAG_READ", 0x02)
        F_WRITE = getattr(bluetooth, "FLAG_WRITE", 0x08)
        F_NOTIFY = getattr(bluetooth, "FLAG_NOTIFY", 0x10)
        U = bluetooth.UUID
        return (
            U(GOTCHA_SVC),
            (
                (U(ATTACK_CHR), F_WRITE),            # Phase 3b (the duel)
                (U(DUEL_CHR), F_READ | F_NOTIFY),    # Phase 3b
                (U(SPOILS_CHR), F_READ),             # Phase 3b
                (U(REVEAL_CHR), F_WRITE),            # Phase 3a
            ),
        )

    def bind_handles(self, ble, handles):
        """Receive the service's value handles (registration order) and size the
        write/read buffers. Called once by ContactExchange._ensure_services."""
        self._ble = ble
        for name, h in zip(GOTCHA_CHR_ORDER, handles):
            self._h[name] = h
        # Write buffers so a REVEAL/ATTACK payload is not truncated, and so the
        # DUEL value we stage for the attacker's poll-read (notify fallback, §5.5)
        # holds a full {s,h,d} state rather than the ~20-byte default.
        for name in ("attack", "reveal", "duel"):
            h = self._h.get(name)
            if h is not None:
                try:
                    ble.gatts_set_buffer(h, 64, True)
                except Exception:
                    pass
        # SPOILS carries soul + inherited target; give it the room the Phase-0
        # spike confirmed (512-byte gatts_set_buffer succeeded).
        h = self._h.get("spoils")
        if h is not None:
            try:
                ble.gatts_set_buffer(h, 512, True)
            except Exception:
                pass

    def on_radio_off(self):
        """BLE was deactivated -> NimBLE's gatts table is cleared and our handles
        are stale. Drop them so a fresh registration (ContactExchange.ensure_radio)
        rebinds them."""
        self._h = {}
        self._ble = None
        self._central = None
        self._pending = []
        self._pending_attacks = []

    # ---- the IRQ dispatch target (called by BLEProximity._irq) -------------
    def handle_irq(self, event, data):
        """Handle GATT-server events while BLEProximity owns the radio. Never
        raises: a BLE IRQ must not crash the scan path. A valid REVEAL write is
        queued (parse + flash happen off the IRQ, on the owner's tick)."""
        import bluetooth
        try:
            if event == getattr(bluetooth, "_IRQ_GATTS_WRITE", 3):
                self.dbg_write += 1
                self.dbg_write_h = data[1]
                if data[1] == self._h.get("reveal"):
                    self._on_reveal_write(data[1])
                elif data[1] == self._h.get("attack"):
                    self._on_attack_write(data[1], data[0])
            elif event == getattr(bluetooth, "_IRQ_CENTRAL_CONNECT", 1):
                self.dbg_central += 1
                self._central = data[0]            # a hunter/attacker connected (§5.5)
            elif event == getattr(bluetooth, "_IRQ_CENTRAL_DISCONNECT", 2):
                self._central = None
        except Exception:
            pass

    def _on_reveal_write(self, value_handle):
        if self._ble is None:
            return
        try:
            raw = self._ble.gatts_read(value_handle)
        except Exception:
            return
        import gotcha
        parsed = gotcha.parse_reveal_payload(raw)
        if parsed is None:
            return                          # garbage write -> drop silently
        # Queue for the owner's tick; the IRQ must not do lvgl/event work. Keep at
        # most one pending -- a flash already in flight is enough, and reveals are
        # idempotent for the victim (no soul, no state change).
        if not self._pending:
            self._pending.append(parsed)

    def drain_reveals(self):
        """Pop the pending inbound reveal (if any) for the owner's tick to action.
        Fires on_reveal(parsed). Returns the parsed payload, or None."""
        if not self._pending:
            return None
        parsed = self._pending.pop(0)
        if self.on_reveal is not None:
            try:
                self.on_reveal(parsed)
            except Exception:
                pass
        return parsed

    # ---- the duel (Phase 3b, §5.3) -----------------------------------------
    def _on_attack_write(self, value_handle, conn):
        if self._ble is None:
            return
        try:
            raw = self._ble.gatts_read(value_handle)
        except Exception:
            return
        import gotcha
        parsed = gotcha.parse_attack_payload(raw)
        if parsed is None:
            return                          # garbage write -> drop silently
        # Keep at most one pending ATTACK -- a duel already begun is enough and a
        # second ATTACK during a live duel is refused anyway (single slot, §5.5).
        if not self._pending_attacks:
            self._pending_attacks.append((parsed, conn))

    def drain_attacks(self):
        """Pop the pending inbound ATTACK (if any) for the owner's tick to action.
        Fires on_attack(parsed, conn). Returns (parsed, conn), or None."""
        if not self._pending_attacks:
            return None
        item = self._pending_attacks.pop(0)
        if self.on_attack is not None:
            try:
                self.on_attack(item[0], item[1])
            except Exception:
                pass
        return item

    def notify_duel(self, data, conn=None):
        """Push a DUEL notify to the attacker (victim -> attacker, §5.3). `data`
        is a gotcha.build_duel_payload() byte/str. Uses the live central conn by
        default. Returns True on success, never raises."""
        if self._ble is None:
            return False
        c = self._central if conn is None else conn
        h = self._h.get("duel")
        if c is None or h is None:
            return False
        try:
            if isinstance(data, str):
                data = data.encode("utf-8")
            # Stage the value first so an attacker poll-read (the notify fallback,
            # duel_session §5.5) returns the current state, then push the notify.
            try:
                self._ble.gatts_write(h, data)
            except Exception:
                pass
            self._ble.gatts_notify(c, h, data)
            return True
        except Exception:
            return False

    def set_spoils(self, data):
        """Stage the SPOILS value so the attacker's gattc_read returns it (§5.3).
        `data` is a gotcha.build_spoils_payload() byte/str. Never raises."""
        if self._ble is None:
            return False
        h = self._h.get("spoils")
        if h is None:
            return False
        try:
            if isinstance(data, str):
                data = data.encode("utf-8")
            self._ble.gatts_write(h, data)
            return True
        except Exception:
            return False

    def central_conn(self):
        """The connected central's conn_handle (the attacker mid-duel), or None.
        The victim's DuelState reads `central_conn() is not None` as link_up: a
        link drop before the hold elapses is the §5.3 escape (link-drop dodge)."""
        return self._central

    def is_busy(self):
        """A central is connected -> the single connection slot is taken (§5.5):
        the loop should skip _update_leds (a WS2812 lights.write() disables IRQs
        and would starve the link) and a hunter-side connect should be refused."""
        return self._central is not None
