import os, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
from PySide6.QtGui import QFont, QCloseEvent
import main as app_main

app = QApplication([])
app.setStyleSheet(app_main.QSS)
app.setFont(QFont("Segoe UI", 10))

from playlistflow.config import display_settings, save_env, load_env, env_path
from playlistflow.settings import SettingsDialog
from playlistflow.mainwindow import MainWindow
from playlistflow.domain import Track, classify_tempo
import playlistflow.domain as dom
from playlistflow.store import Store

# --- defaults out of an untouched env ---------------------------------------
d = display_settings({})
print("defaults:", d)

# --- dialog: tabs exist, values round-trip ----------------------------------
dlg = SettingsDialog()
v = dlg.values()
print("dialog display values:", {k: v[k] for k in v if k.startswith(("GRAPH", "FIT", "FELT", "TEMPO", "WARN", "PREVIEW", "AUTOSAVE"))})

# --- mainwindow applies settings --------------------------------------------
w = MainWindow()
print("chart fixed_max:", w.chart.fixed_max, "| tail default:", w.player.tail.value(),
      "| autosave ms:", w._autosave.interval())
print("domain fold:", dom.FELT_FOLD, "| tol:", dom.TEMPO_TOL, "| warn:", dom.WARN_BOTH)

# tolerance switch reclassifies
w.env = dict(w.env); w.env["TEMPO_TOLERANCE"] = "tight"
w._apply_display()
print("tight applied:", dom.TEMPO_TOL, "| 68->129:", classify_tempo(68, 129))
w.env["TEMPO_TOLERANCE"] = "normal"; w._apply_display()

# fit override
w.env["FIT_OVERRIDES_MAX"] = "1"; w._apply_display()
w.zoom_fit()
print("fit_scale after Fit:", w.chart.fit_scale)
w.env["FIT_OVERRIDES_MAX"] = "0"; w._apply_display()
print("fit_scale after override off:", w.chart.fit_scale)

# chart scaling: fixed ceiling vs fit
w.tracks = [Track(title="a", artist="x", bpm=100, key="8A", source="manual"),
            Track(title="b", artist="x", bpm=140, key="8A", source="manual")]
w.chart.fixed_max = 200.0; w.chart.fit_scale = False
from playlistflow.domain import seams
w.chart.set_data(w.tracks, seams(w.tracks), False, -1)
hi, lo = w.chart._scale()
print("fixed scale hi:", hi, "(expect 200)")
w.chart.set_fit_scale(True)
hi, lo = w.chart._scale()
print("fit scale hi  :", hi, "(expect 140)")

# --- exit prompt --------------------------------------------------------------
tmp = tempfile.mkdtemp(prefix="pfdisp")
_real = w.prefs.storage_dir
w.prefs.storage_dir = tmp
w.store = Store(tmp)
w.current_name = "T"
w.snapshot()          # marks dirty
answers = []
QMessageBox.question = staticmethod(lambda *a, **k: answers.pop(0))

answers.append(QMessageBox.Cancel)
ev = QCloseEvent(); w.closeEvent(ev)
print("cancel keeps open:", not ev.isAccepted())

answers.append(QMessageBox.Save)
ev = QCloseEvent(); w.closeEvent(ev)
print("save closes:", ev.isAccepted(), "| dirty now:", w._dirty,
      "| file written:", os.path.exists(os.path.join(tmp, "T.json")))

w.snapshot()
answers.append(QMessageBox.Discard)
ev = QCloseEvent(); w.closeEvent(ev)
print("discard closes:", ev.isAccepted())

w.prefs.storage_dir = _real
shutil.rmtree(tmp, ignore_errors=True)
print("done, prefs restored")
