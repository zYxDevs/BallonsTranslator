import sys
import argparse
import os.path as osp
import os

import importlib
import re
import subprocess
import importlib.util
import pkg_resources

python = sys.executable
git = os.environ.get('GIT', "git")
skip_install = False
index_url = os.environ.get('INDEX_URL', "")
QT_APIS = ['pyqt5', 'pyqt6']
stored_commit_hash = None

REQ_WIN = [
    'pywin32'
]

parser = argparse.ArgumentParser()
parser.add_argument("--reinstall-torch", action='store_true', help="launch.py argument: install the appropriate version of torch even if you have some version already installed")
parser.add_argument("--proj-dir", default='', type=str, help='Open project directory on startup')
parser.add_argument("--qt-api", default='', choices=QT_APIS, help='Set qt api')
parser.add_argument("--requirements", default='requirements.txt')
args, _ = parser.parse_known_args()

def is_installed(package):
    try:
        spec = importlib.util.find_spec(package)
    except ModuleNotFoundError:
        return False

    return spec is not None


def run(command, desc=None, errdesc=None, custom_env=None, live=False):
    if desc is not None:
        print(desc)

    if live:
        result = subprocess.run(command, shell=True, env=os.environ if custom_env is None else custom_env)
        if result.returncode != 0:
            raise RuntimeError(f"""{errdesc or 'Error running command'}.
Command: {command}
Error code: {result.returncode}""")

        return ""

    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, env=os.environ if custom_env is None else custom_env)

    if result.returncode != 0:

        message = f"""{errdesc or 'Error running command'}.
Command: {command}
Error code: {result.returncode}
stdout: {result.stdout.decode(encoding="utf8", errors="ignore") if len(result.stdout)>0 else '<empty>'}
stderr: {result.stderr.decode(encoding="utf8", errors="ignore") if len(result.stderr)>0 else '<empty>'}
"""
        raise RuntimeError(message)

    return result.stdout.decode(encoding="utf8", errors="ignore")


def run_pip(args, desc=None):
    if skip_install:
        return

    index_url_line = f' --index-url {index_url}' if index_url != '' else ''
    return run(f'"{python}" -m pip {args} --prefer-binary{index_url_line}', desc=f"Installing {desc}", errdesc=f"Couldn't install {desc}", live=True)


def commit_hash():
    global stored_commit_hash

    if stored_commit_hash is not None:
        return stored_commit_hash

    try:
        stored_commit_hash = run(f"{git} rev-parse HEAD").strip()
    except Exception:
        stored_commit_hash = "<none>"

    return stored_commit_hash


TRANSLATOR_DIR = 'modules/translators'
TRANSLATOR_PATTERN = re.compile(r'trans_(.*?).py') 
def load_translators(translators = None):
    if translators is None:
        translators = os.listdir(TRANSLATOR_DIR)

    for translator in translators:
        if TRANSLATOR_PATTERN.match(translator) is not None:
            importlib.import_module('modules.translators.' + translator.replace('.py', ''))


def load_modules():
    load_translators()

def main():
    from utils.logger import setup_logging, logger as LOGGER

    # parser = argparse.ArgumentParser()


    if not args.qt_api in QT_APIS:
        os.environ['QT_API'] = 'pyqt6'
    else:
        os.environ['QT_API'] = args.qt_api

    if sys.platform == 'darwin':
        os.environ['QT_API'] = 'pyqt6'
        LOGGER.info('running on macOS, set QT_API to pyqt6')

    if sys.platform == 'win32':
        import ctypes
        myappid = u'BalloonsTranslator' # arbitrary string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    import qtpy
    from qtpy.QtWidgets import QApplication
    from qtpy.QtCore import QTranslator, QLocale, Qt
    from qtpy.QtGui import QIcon
    from qtpy.QtGui import  QGuiApplication, QIcon, QFont

    from ui import constants as C
    if qtpy.API_NAME[-1] == '6':
        C.FLAG_QT6 = True
    else:
        C.FLAG_QT6 = False
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True) #enable highdpi scaling
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True) #use highdpi icons
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    os.chdir(C.PROGRAM_PATH)

    setup_logging(C.LOGGING_PATH)

    load_modules()

    app = QApplication(sys.argv)
    translator = QTranslator()
    translator.load(
        QLocale.system().name(),
        osp.dirname(osp.abspath(__file__)) + "/translate",
    )
    app.installTranslator(translator)

    ps = QGuiApplication.primaryScreen()
    C.LDPI = ps.logicalDotsPerInch()
    C.SCREEN_W = ps.geometry().width()
    C.SCREEN_H = ps.geometry().height()
    yahei = QFont('Microsoft YaHei UI')
    if yahei.exactMatch():
        QGuiApplication.setFont(yahei)

    from ui.mainwindow import MainWindow
    ballontrans = MainWindow(app, open_dir=args.proj_dir)
    ballontrans.setWindowIcon(QIcon(C.ICON_PATH))
    ballontrans.show()
    ballontrans.resetStyleSheet()
    sys.exit(app.exec())

def prepare_environment():

    req_updated = False
    if sys.platform == 'win32':
        for req in REQ_WIN:
            try:
                pkg_resources.require(req)
            except Exception:
                run_pip(f"install {req}", req)
                req_updated = True

    torch_command = os.environ.get('TORCH_COMMAND', "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118")
    if args.reinstall_torch or not is_installed("torch") or not is_installed("torchvision"):
        run(f'"{python}" -m {torch_command}', "Installing torch and torchvision", "Couldn't install torch", live=True)
        req_updated = True
    try:
        pkg_resources.require(open(args.requirements,mode='r', encoding='utf8'))
    except Exception:
        run_pip(f"install -r {args.requirements}", "requirements")
        req_updated = True

    if req_updated:
        import site
        importlib.reload(site)

if __name__ == '__main__':

    from utils import appinfo

    commit = commit_hash()

    print('py version: ', sys.version)
    print('py executable: ', sys.executable)
    print(f'version: {appinfo.version}')
    print(f'branch: {appinfo.branch}')
    print(f"Commit hash: {commit}")

    prepare_environment()
    main()