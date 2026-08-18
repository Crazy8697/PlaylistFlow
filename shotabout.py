import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from playlistflow.mainwindow import AboutDialog
import main as app_main

app = QApplication([])
app.setStyleSheet(app_main.QSS)
d = AboutDialog()
d.resize(560, 470)
d.show()
d.grab().save("shot_about.png")
print("wrote shot_about.png")
