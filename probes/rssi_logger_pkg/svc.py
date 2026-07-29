# svc.py -- boot service: on boot, start the RSSI logger task.
#
# Throwaway one-app boot service for the Gotcha RSSI-trend spike. Deploy this
# package to /apps/rssi.logger/, write /rssi_cfg.json, reset: the badge boots and
# logs every HSNT advert (or the named target) to /rssi_log.csv on flash. Pull the
# file later over USB; remove the package when done. Built like beacon_service.py.
import sys

APP_DIR = "/apps/rssi.logger"
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

try:
    from mpos import Service, TaskManager
except ImportError:              # host-side unit tests: no mpos on CPython
    TaskManager = None

    class Service:
        def __init__(self):
            pass


class RssiLoggerService(Service):
    def __init__(self):
        super().__init__()
        self._task = None

    def onStart(self, intent=None):
        try:
            import rssi_log
            self._task = TaskManager.create_task(rssi_log.run())
        except Exception as e:
            print("rssi.logger onStart error", repr(e))

    def onDestroy(self):
        if self._task is not None:
            try:
                self._task.cancel()
            except Exception:
                pass
            self._task = None
