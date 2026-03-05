import omni.ext
import omni.kit.app
from com.ov.core.service import get_orbit_service
from .graph_ui import NodeGraphUI

class OrbitNodeGraphExtension(omni.ext.IExt):
    def on_startup(self, ext_id):
        self._svc = get_orbit_service()
        self._ui = NodeGraphUI(self._svc)
        self._app = omni.kit.app.get_app()
        self._update_sub = self._app.get_update_event_stream().create_subscription_to_pop(
            self._on_update
        )
        self._frame = 0
        print("[OrbitNodeGraph] started")

    def on_shutdown(self):
        if self._update_sub:
            self._update_sub.unsubscribe()
        if self._ui:
            self._ui.destroy()
        print("[OrbitNodeGraph] shutdown")

    def _on_update(self, e):
        self._frame += 1
        if self._frame % 30 == 0:   # refresh graph every 30 frames
            self._ui.refresh()