import os
import re
import sys
import shutil
import zipfile
import subprocess
import time
import traceback
import tempfile

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

if sys.stdout is None: sys.stdout = open(os.devnull, 'w')
if sys.stderr is None: sys.stderr = open(os.devnull, 'w')

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QFileDialog, QProgressBar,
    QGroupBox, QFormLayout, QLineEdit, QSplitter, QDialog
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor

DEFAULTS = {
    "main_cpp":     r"D:\Marvel_Future_Fight\NativeModMenu-main\app\src\main\jni\Main.cpp",
    "dumper":       r"D:\Marvel_Future_Fight\Tools\Il2CppDumper-win-v6.7.46\Il2CppDumper.exe",
    "ndk_build":    r"C:\Users\arunk\AppData\Local\Android\Sdk\ndk\28.2.13676358\ndk-build.cmd",
    "gradlew":      r"D:\Marvel_Future_Fight\NativeModMenu-main\gradlew.bat",
    "gradle_apk":   r"D:\Marvel_Future_Fight\NativeModMenu-main\app\build\outputs\apk\debug\app-debug.apk",
    "apksigner":    r"C:\Users\arunk\AppData\Local\Android\Sdk\build-tools\34.0.0\apksigner.bat",
    "keystore":     r"C:\Users\arunk\.android\debug.keystore",
    "project_root": r"D:\Marvel_Future_Fight\NativeModMenu-main",
    "output_dir":   r"D:\Marvel_Future_Fight",
    "build_backend": "gradle",
}


# ============================================================
# CUSTOM DARK MESSAGE BOX
# ============================================================
class DarkMessageBox(QDialog):
    def __init__(self, title, message, is_error=False):
        super().__init__()
        self.setWindowTitle(title)
        self.setFixedSize(440, 200)
        self.setStyleSheet("""
            QDialog { background: #1e1e2e; border: 1px solid #313244; border-radius: 10px; }
            QLabel { color: #cdd6f4; font-family: 'Segoe UI'; font-size: 13px; }
            QPushButton {
                background: #89b4fa; color: #1e1e2e; border: none;
                border-radius: 6px; padding: 8px 24px; font-weight: bold; font-size: 13px;
            }
            QPushButton:hover { background: #b4befe; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        lbl = QLabel(message)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)

        layout.addStretch()

        btn = QPushButton("OK")
        btn.clicked.connect(self.accept)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)


# ============================================================
# WORKER THREAD
# ============================================================
class BuildWorker(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(int)
    finished_signal = Signal(bool, str)

    def __init__(self, apk_path, config):
        super().__init__()
        self.apk_path = apk_path
        self.config = config
        self.temp_dir = "temp_extract"
        self.dump_dir = "dump_output"
        self.backup_dir = "backups"
        self.tmp_lib = "temp_tphlib"
        self.start_time = None

    def log(self, msg):
        e = f"[{time.time() - self.start_time:.1f}s] " if self.start_time else ""
        self.log_signal.emit(e + msg)

    def run(self):
        self.start_time = time.time()
        try:
            self.process()
            self.cleanup()
            total = time.time() - self.start_time
            self.finished_signal.emit(True, f"Build completed in {total:.1f}s.")
        except Exception as e:
            self.log(f"[!] FATAL ERROR: {e}")
            self.log(traceback.format_exc())
            self.finished_signal.emit(False, str(e))

    def cleanup(self):
        self.log("[*] Cleaning temp files...")
        for d in [self.temp_dir, self.dump_dir]:
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)
                self.log(f"    [+] Removed {d}/")
        if os.path.exists(self.tmp_lib):
            try: os.remove(self.tmp_lib)
            except: pass

    # ---------- MAIN PIPELINE ----------
    def process(self):
        apk = os.path.abspath(self.apk_path)
        self.log(f"[*] Input APK: {apk}")
        self.log(f"[*] Size: {os.path.getsize(apk)/1048576:.2f} MB")
        self.log(f"[*] Build backend: {self.config.get('build_backend', 'gradle')}")
        self.progress_signal.emit(5)

        os.makedirs(self.backup_dir, exist_ok=True)
        dest = os.path.join(self.backup_dir, "ORIGINAL_TPH.apk")
        self.log(f"[*] Backup → {dest}")
        shutil.copy(apk, dest)
        self.progress_signal.emit(10)

        dump_path = self.extract_and_dump(apk)
        self.progress_signal.emit(40)

        rvas = self.get_rvas_from_dump(dump_path)
        self.progress_signal.emit(50)

        self.update_main_cpp(rvas)
        self.progress_signal.emit(60)

        backend = self.config.get("build_backend", "gradle").lower()
        if backend == "gradle":
            so_path = self.build_so_via_gradle()
        else:
            so_path = self.build_so_via_ndk()
        self.progress_signal.emit(80)

        self.verify_so(so_path)

        out_apk = self.inject_and_rename(so_path, apk)
        self.progress_signal.emit(95)

        self.sign_apk(out_apk)
        self.progress_signal.emit(100)
        self.log(f"[+] DONE: {out_apk}")

    # ---------- STEP 1: extract + dump ----------
    def extract_and_dump(self, apk_path):
        self.log("[*] Extracting libs...")
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.makedirs(self.temp_dir)
        so_path = meta_path = None
        with zipfile.ZipFile(apk_path) as apk:
            for name in apk.namelist():
                if "libil2cpp.so" in name and "arm64" in name:
                    apk.extract(name, self.temp_dir)
                    so_path = os.path.join(self.temp_dir, name)
                if "global-metadata.dat" in name:
                    apk.extract(name, self.temp_dir)
                    meta_path = os.path.join(self.temp_dir, name)
        if not so_path or not meta_path:
            raise Exception("Missing .so or .dat")

        self.log("[*] Running Il2CppDumper...")
        shutil.rmtree(self.dump_dir, ignore_errors=True)
        os.makedirs(self.dump_dir)
        dumper_dir = os.path.dirname(os.path.abspath(self.config["dumper"]))
        result = subprocess.run(
            [os.path.abspath(self.config["dumper"]),
             os.path.abspath(so_path),
             os.path.abspath(meta_path),
             os.path.abspath(self.dump_dir)],
            cwd=dumper_dir, capture_output=True, text=True, input="",
            creationflags=CREATE_NO_WINDOW
        )
        dump_cs = os.path.join(self.dump_dir, "dump.cs")
        if not os.path.exists(dump_cs):
            raise Exception(f"Dumper failed:\n{result.stderr}")
        self.log("    [+] dump.cs generated")
        return dump_cs

    # ---------- STEP 2: parse RVAs ----------
        # ---------- STEP 2: parse RVAs ----------
    def get_rvas_from_dump(self, dump_path):
        self.log("[*] Parsing RVAs...")
        targets = {
            "HitDamage_Internal": None, 
            "GetSpeed": None, 
            "IsMyPlayer": None,
            "ClickSkill_UpdateSkillCooltime": None,
            "SkillManager_UseSkill": None,
            "SkillManager_IsCooltimeRunning": None,
            "SkillManager_IsCooltimeRunningWithSkillId": None,
            "SkillManager_SetSkillCoolTime": None
        }
        
        with open(dump_path, encoding='utf-8') as f:
            lines = f.readlines()

        current_class = ""
        
        for i, line in enumerate(lines):
            # 1. Detect class changes (e.g., "public class AI : MonoBehaviour")
            class_match = re.search(r'\bclass\s+([A-Za-z0-9_]+)', line)
            if class_match:
                current_class = class_match.group(1)

            # 2. Find the RVA line
            if "// RVA:" not in line:
                continue

            rva_match = re.search(r'// RVA: (0x[0-9a-fA-F]+)', line)
            if not rva_match:
                continue
            current_rva = rva_match.group(1)

            # 3. Look at the next line for the function signature
            if i + 1 < len(lines):
                func_line = lines[i+1]
                
                # --- Match IsMyPlayer (found in AI class) ---
                if re.search(r'\bget_IsMyPlayer\s*\(', func_line) or re.search(r'\bIsMyPlayer\s*\(', func_line):
                    targets["IsMyPlayer"] = current_rva
                    
                # --- Match AI functions ---
                elif current_class == "AI":
                    if re.search(r'\bHitDamage_Internal\s*\(', func_line):
                        targets["HitDamage_Internal"] = current_rva
                    elif re.search(r'\bGetSpeed\s*\(', func_line):
                        targets["GetSpeed"] = current_rva
                        
                # --- Match ClickSkill functions ---
                elif current_class == "ClickSkill":
                    if re.search(r'\bUpdateSkillCooltime\s*\(', func_line):
                        targets["ClickSkill_UpdateSkillCooltime"] = current_rva
                        
                # --- Match SkillManager functions ---
                elif current_class == "SkillManager":
                    if re.search(r'\bUseSkill\s*\(', func_line):
                        targets["SkillManager_UseSkill"] = current_rva
                    elif re.search(r'\bIsCooltimeRunningWithSkillId\s*\(', func_line):
                        targets["SkillManager_IsCooltimeRunningWithSkillId"] = current_rva
                    elif re.search(r'\bIsCooltimeRunning\s*\(', func_line):
                        targets["SkillManager_IsCooltimeRunning"] = current_rva
                    elif re.search(r'\bSetSkillCoolTime\s*\(', func_line):
                        targets["SkillManager_SetSkillCoolTime"] = current_rva

        for func, rva in targets.items():
            if rva:
                self.log(f"    [+] {func}: {rva}")
            else:
                self.log(f"    [!] {func}: NOT FOUND")

        if not all(targets.values()):
            raise Exception("Missing some RVAs. Check the dump or update the script.")
        return targets
    
    # ---------- STEP 3: patch Main.cpp ----------
    def update_main_cpp(self, rvas):
        path = self.config["main_cpp"]
        self.log("[*] Updating Main.cpp...")
        if not os.path.exists(path):
            raise Exception(f"Missing: {path}")

        with open(path, encoding="utf-8") as f:
            source = f.read()

        # BULLETPROOF REGEX PATTERNS
        patterns = {
            "IsMyPlayer": (
                r'(get_IsMyPlayer\s*=\s*\(t_AIFn\)\s*KittyMemory::getAbsoluteAddress\(\s*"libil2cpp\.so"\s*,\s*)(0x[0-9a-fA-F]+)'
            ),
            "HitDamage_Internal": (
                r'("libil2cpp\.so"\s*,\s*")(0x[0-9a-fA-F]+)("\s*,\s*hooked_HitDamage_Internal)'
            ),
            "GetSpeed": (
                r'("libil2cpp\.so"\s*,\s*")(0x[0-9a-fA-F]+)("\s*,\s*hooked_GetSpeed)'
            ),
            "ClickSkill_UpdateSkillCooltime": (
                r'("libil2cpp\.so"\s*,\s*")(0x[0-9a-fA-F]+)("\s*,\s*hooked_UpdateSkillCooltime)'
            ),
            "SkillManager_UseSkill": (
                r'("libil2cpp\.so"\s*,\s*")(0x[0-9a-fA-F]+)("\s*,\s*hooked_SmUseSkill)'
            ),
            "SkillManager_IsCooltimeRunning": (
                r'("libil2cpp\.so"\s*,\s*")(0x[0-9a-fA-F]+)("\s*,\s*hooked_IsCooltimeRunning\b)'
            ),
            "SkillManager_IsCooltimeRunningWithSkillId": (
                r'("libil2cpp\.so"\s*,\s*")(0x[0-9a-fA-F]+)("\s*,\s*hooked_IsCooltimeRunningWithSkillId)'
            ),
            "SkillManager_SetSkillCoolTime": (
                r'("libil2cpp\.so"\s*,\s*")(0x[0-9a-fA-F]+)("\s*,\s*hooked_SetSkillCoolTime)'
            ),
        }

        backup_path = path + ".bak"
        if not os.path.exists(backup_path):
            with open(backup_path, "w", encoding="utf-8") as f:
                f.write(source)
            self.log(f"    [+] Backup → {backup_path}")

        any_replaced = False
        for name, pattern in patterns.items():
            matches = list(re.finditer(pattern, source))

            if len(matches) != 1:
                self.log(f"    [!] {name}: expected 1 match, found {len(matches)} — skipped")
                continue

            match = matches[0]
            groups = match.groups()

            if len(groups) == 2:
                replacement = match.group(1) + rvas[name]
            elif len(groups) == 3:
                replacement = (
                    match.group(1)
                    + rvas[name]
                    + match.group(3)
                )
            else:
                self.log(f"    [!] {name}: unexpected capture groups — skipped")
                continue

            current = match.group(2)
            if current.lower() == rvas[name].lower():
                self.log(f"    [=] {name} already {rvas[name]}")
                any_replaced = True # Mark as replaced even if it's the same, to bypass the safety check
                continue

            source = (
                source[:match.start()]
                + replacement
                + source[match.end():]
            )
            self.log(f"    [+] {name}: {current} → {rvas[name]}")
            any_replaced = True

        if any_replaced:
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
            self.log("    [+] Main.cpp written")
        else:
            raise Exception("No RVAs were replaced! The regex patterns didn't match the Main.cpp structure. Check your Main.cpp formatting.")

    # ---------- STEP 4a: build via Gradle ----------
    def build_so_via_gradle(self):
        self.log("[*] Building via Gradle: clean → :app:generateMenuDexDebug → assembleDebug")
        gradlew = self.config.get("gradlew")
        if not gradlew or not os.path.exists(gradlew):
            raise Exception(f"gradlew not found: {gradlew}")

        root = self.config["project_root"]
        apk_out = self.config["gradle_apk"]

        for stale in [
            os.path.join(root, "app", "build", "intermediates", "cxx"),
            os.path.join(root, "app", "build", "intermediates", "ndkBuild"),
            os.path.join(root, "app", "build", "intermediates", "stripped_native_libs"),
            os.path.join(root, "app", "build", "intermediates", "merged_native_libs"),
            os.path.join(root, "libs"),
            os.path.join(root, "obj"),
        ]:
            if os.path.exists(stale):
                shutil.rmtree(stale, ignore_errors=True)
                self.log(f"    [+] Cleared {stale}")

        steps = [
            [gradlew, "clean", "--no-daemon", "--console=plain"],
            [gradlew, ":app:generateMenuDexDebug", "--rerun-tasks", "--no-daemon", "--console=plain"],
            [gradlew, "assembleDebug", "--no-daemon", "--console=plain"],
        ]
        labels = ["clean", "generateMenuDexDebug", "assembleDebug"]

        for label, cmd in zip(labels, steps):
            self.log(f"    [>] gradlew {label} ...")
            result = subprocess.run(
                cmd, cwd=root,
                capture_output=True, text=True,
                creationflags=CREATE_NO_WINDOW
            )
            if result.returncode != 0:
                tail = "\n".join((result.stdout or "").splitlines()[-40:])
                err = "\n".join((result.stderr or "").splitlines()[-40:])
                self.log(f"[!] GRADLE '{label}' FAILED (rc={result.returncode}):\n"
                         f"--- stdout tail ---\n{tail}\n--- stderr tail ---\n{err}")
                raise Exception(f"Gradle step failed: {label}")
            self.log(f"    [+] {label} OK")

        if not os.path.exists(apk_out):
            raise Exception(f"Expected APK not found after gradle: {apk_out}")

        self.log(f"[*] Extracting libShadow.so from {apk_out} ...")
        tmp = tempfile.mkdtemp(prefix="mff_so_")
        so_found = None
        with zipfile.ZipFile(apk_out) as z:
            for name in z.namelist():
                if name.endswith("lib/arm64-v8a/libShadow.so"):
                    out_path = os.path.join(tmp, "libShadow.so")
                    with open(out_path, "wb") as f:
                        f.write(z.read(name))
                    so_found = out_path
                    self.log(f"    [+] {name}  →  {out_path}  ({os.path.getsize(out_path)} bytes)")
                    break
        if not so_found:
            raise Exception("libShadow.so not found inside app-debug.apk. "
                            "Check externalNativeBuild / Android.mk in your Gradle setup.")
        return so_found

    # ---------- STEP 4b: build via raw ndk-build ----------
    def build_so_via_ndk(self):
        self.log("[*] Building libShadow.so via ndk-build -B ...")
        app_dir = os.path.join(self.config["project_root"], "app")
        main_cpp = self.config["main_cpp"]

        for stale in [
            os.path.join(self.config["project_root"], "libs", "arm64-v8a", "libShadow.so"),
            os.path.join(self.config["project_root"], "obj", "local", "arm64-v8a"),
            os.path.join(app_dir, "build", "intermediates", "cxx"),
            os.path.join(app_dir, "build", "intermediates", "ndkBuild"),
        ]:
            if os.path.isdir(stale):
                shutil.rmtree(stale, ignore_errors=True)
                self.log(f"    [+] Cleared dir {stale}")
            elif os.path.exists(stale):
                os.remove(stale)
                self.log(f"    [+] Cleared file {stale}")

        cmd = [
            self.config["ndk_build"], "-B",
            f"NDK_PROJECT_PATH={self.config['project_root']}",
            f"APP_BUILD_SCRIPT={app_dir}\\src\\main\\jni\\Android.mk",
            f"NDK_APPLICATION_MK={app_dir}\\src\\main\\jni\\Application.mk",
            "APP_ABI=arm64-v8a", "NDK_DEBUG=1",
        ]
        result = subprocess.run(
            cmd, cwd=app_dir,
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW
        )
        if result.returncode != 0:
            err_msg = result.stderr.strip() if result.stderr else result.stdout.strip()
            self.log(f"[!] BUILD ERROR DETAILS:\n{err_msg}")
            raise Exception("Build failed. See details above.")

        candidates = [
            os.path.join(self.config["project_root"], "libs", "arm64-v8a", "libShadow.so"),
            os.path.join(self.config["project_root"], "obj", "local", "arm64-v8a", "libShadow.so"),
        ]

        main_mtime = os.path.getmtime(main_cpp)
        found = None
        for c in candidates:
            if os.path.exists(c):
                mt = os.path.getmtime(c)
                fresh = mt >= main_mtime - 2
                self.log(f"    [{'✓' if fresh else '✗'}] {c}  (mtime {'>=' if fresh else '<'} Main.cpp)")
                if fresh and not found:
                    found = c

        if not found:
            raise Exception(
                "No fresh libShadow.so found after ndk-build. "
                "This means the compiler did NOT actually rebuild Main.cpp — "
                "your old stale .so is still on disk and would be packaged. Refusing to continue.\n"
                f"  main_cpp: {main_cpp}  (mtime {main_mtime})\n"
                f"  candidates checked: {candidates}"
            )
        return found

    # ---------- STEP 5: verify the .so ----------
    def verify_so(self, so_path):
        self.log("[*] Verifying .so does not contain the old dynamic-resolver strings...")
        needles = [b"Failed to resolve IL2CPP API",
                   b"Aborting hook installation",
                   b"il2cpp_domain_get",
                   b"il2cpp_resolve_icall"]
        data = open(so_path, "rb").read()
        hits = [n.decode(errors="replace") for n in needles if n in data]
        if hits:
            raise Exception(
                "The .so still contains resolver strings: " + ", ".join(hits) + "\n"
                "This is the STALE build. It will print 'Resolver CRITICAL / Aborting hook installation' "
                "at runtime and do nothing. Force a clean rebuild."
            )
        if b"All hooks installed" not in data and b"Hooking HitDamage_Internal" not in data:
            self.log("    [!] Warning: could not find expected log strings in .so — verify manually.")
        self.log("    [+] .so looks like the manual-RVA build.")

    # ---------- STEP 6: inject ----------
    def inject_and_rename(self, so_path, apk_path):
        self.log("[*] Injecting...")
        shutil.copy(so_path, self.tmp_lib)

        temp_apk = apk_path + ".temp"
        shutil.copy(apk_path, temp_apk)

        out_dir = self.config.get("output_dir", r"D:\Marvel_Future_Fight")
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        out = os.path.join(out_dir, "MODDED_TPH.apk")

        temp_modded = out + ".modding"
        with zipfile.ZipFile(temp_apk) as zin, zipfile.ZipFile(temp_modded, 'w') as zout:
            for item in zin.infolist():
                if item.filename != "assets/tphlib":
                    zout.writestr(item, zin.read(item.filename))
            zout.write(self.tmp_lib, "assets/tphlib")

        if os.path.exists(out):
            try:
                os.remove(out)
                self.log(f"    [*] Replaced existing {out}")
            except Exception as e:
                self.log(f"    [!] Could not delete existing file: {e}")

        os.remove(temp_apk)
        os.rename(temp_modded, out)
        os.remove(self.tmp_lib)

        self.log(f"    [+] Output: {out}")
        return out

    # ---------- STEP 7: sign ----------
    def sign_apk(self, apk_path):
        self.log("[*] Signing (forcing v2 & v3)...")
        cmd = [
            self.config["apksigner"], "sign",
            "--ks", self.config["keystore"],
            "--ks-pass", "pass:android",
            "--v2-signing-enabled", "true",
            "--v3-signing-enabled", "true",
            apk_path
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            err_msg = r.stderr.strip() if r.stderr else r.stdout.strip()
            self.log(f"[!] SIGN ERROR DETAILS:\n{err_msg}")
            raise Exception("Sign failed")
        self.log("    [+] Signed OK.")

        idsig_path = apk_path + ".idsig"
        if os.path.exists(idsig_path):
            try:
                os.remove(idsig_path)
                self.log("    [+] Removed .idsig file")
            except Exception as e:
                self.log(f"    [!] Could not remove .idsig: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MFF Auto-Modder")
        self.resize(1150, 580)
        self.setAcceptDrops(True)
        self.apk_path = None
        self.config = DEFAULTS.copy()
        self.setWindowIcon(self.make_icon())
        self.setStyleSheet(self.style())
        self.build_ui()

    def make_icon(self):
        pix = QPixmap(64, 64)
        pix.fill(QColor("#1e1e2e"))
        p = QPainter(pix)
        p.setPen(QColor("#89b4fa"))
        p.setFont(QFont("Segoe UI", 40, QFont.Bold))
        p.drawText(pix.rect(), Qt.AlignCenter, "⚡")
        p.end()
        return QIcon(pix)

    def style(self):
        return """
            QMainWindow { background: #1e1e2e; }
            QWidget { color: #cdd6f4; font-family: 'Segoe UI'; font-size: 13px; }
            QLabel#title { font-size: 22px; font-weight: bold; color: #89b4fa; }
            QLabel#subtitle { font-size: 11px; color: #6c7086; }
            QLabel#dropzone {
                border: 2px dashed #585b70; border-radius: 12px;
                background: #181825; color: #6c7086; font-size: 13px;
            }
            QLabel#dropzone:hover { border-color: #89b4fa; color: #89b4fa; }
            QGroupBox {
                color: #cdd6f4; border: 1px solid #313244;
                border-radius: 8px; margin-top: 8px;
                padding-top: 10px; font-weight: bold; font-size: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px;
                padding: 0 6px; color: #89b4fa;
            }
            QLineEdit {
                background: #313244; color: #cdd6f4;
                border: 1px solid #45475a; border-radius: 6px;
                padding: 4px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #89b4fa; }
            QPushButton#buildBtn {
                background: #89b4fa; color: #1e1e2e;
                border: none; border-radius: 6px;
                padding: 10px; font-size: 14px; font-weight: bold;
            }
            QPushButton#buildBtn:hover { background: #b4befe; }
            QPushButton#buildBtn:disabled { background: #45475a; color: #6c7086; }
            QPushButton#browseBtn {
                background: #313244; color: #cdd6f4;
                border: 1px solid #45475a; border-radius: 6px;
            }
            QPushButton#browseBtn:hover { background: #45475a; }
            QProgressBar {
                background: #313244; border: none; border-radius: 6px;
                height: 24px; text-align: center; color: #cdd6f4; font-size: 12px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #89b4fa, stop:1 #cba6f7);
                border-radius: 6px;
            }
            QTextEdit {
                background: #11111b; color: #cdd6f4;
                border: 1px solid #313244; border-radius: 8px;
                font-family: 'Consolas'; font-size: 12px; padding: 8px;
            }
        """

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(6)

        header = QHBoxLayout()
        logo = QLabel("⚡")
        logo.setStyleSheet("font-size: 30px; color: #89b4fa;")
        header.addWidget(logo)
        tb = QVBoxLayout()
        t = QLabel("MFF Auto-Modder")
        t.setObjectName("title")
        s = QLabel("Drop an APK → fully automated mod pipeline")
        s.setObjectName("subtitle")
        tb.addWidget(t); tb.addWidget(s)
        header.addLayout(tb); header.addStretch()
        main_layout.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(6)

        self.drop_label = QLabel("📦  Drop APK here (or click)")
        self.drop_label.setObjectName("dropzone")
        self.drop_label.setAlignment(Qt.AlignCenter)
        self.drop_label.setFixedHeight(70)
        self.drop_label.setCursor(Qt.PointingHandCursor)
        self.drop_label.mousePressEvent = self.browse_apk
        left_layout.addWidget(self.drop_label)

        g = QGroupBox("⚙  Configuration")
        gl = QFormLayout(); gl.setSpacing(4)
        self.config_fields = {}
        for key in ["main_cpp", "dumper", "ndk_build", "gradlew", "gradle_apk",
                    "apksigner", "keystore", "project_root", "output_dir", "build_backend"]:
            row = QHBoxLayout()
            fld = QLineEdit(self.config[key])
            b = QPushButton("…"); b.setObjectName("browseBtn"); b.setFixedWidth(24)
            b.clicked.connect(lambda c, f=fld, k=key: self.browse_file(f, k))
            row.addWidget(fld); row.addWidget(b)
            gl.addRow(key.replace("_", " ").title() + ":", row)
            self.config_fields[key] = fld
        g.setLayout(gl)
        left_layout.addWidget(g)

        self.build_btn = QPushButton("🚀  Start Build")
        self.build_btn.setObjectName("buildBtn")
        self.build_btn.setFixedHeight(40)
        self.build_btn.setEnabled(False)
        self.build_btn.clicked.connect(self.start_build)
        left_layout.addWidget(self.build_btn)

        self.progress = QProgressBar(); self.progress.setValue(0)
        left_layout.addWidget(self.progress)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(4)

        lbl = QLabel("📋  Build Log")
        lbl.setStyleSheet("color: #89b4fa; font-weight: bold;")
        right_layout.addWidget(lbl)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        right_layout.addWidget(self.log_view, stretch=1)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([550, 550])

        main_layout.addWidget(splitter, stretch=1)

    def browse_file(self, field, key):
        if key == "keystore":
            p, _ = QFileDialog.getOpenFileName(self, "Keystore", "", "*.*")
        elif key in ("project_root", "output_dir"):
            p = QFileDialog.getExistingDirectory(self, "Select Directory")
        else:
            p, _ = QFileDialog.getOpenFileName(self, "File", "", "*.*")
        if p: field.setText(p)

    def browse_apk(self, e):
        p, _ = QFileDialog.getOpenFileName(self, "Select APK", "", "APK (*.apk)")
        if p: self.set_apk(p)

    def set_apk(self, path):
        self.apk_path = path
        n = os.path.basename(path)
        mb = os.path.getsize(path) / 1048576
        self.drop_label.setText(f"✅  {n} ({mb:.2f} MB)")
        self.drop_label.setStyleSheet("""
            QLabel#dropzone {
                border: 2px solid #a6e3a1; border-radius: 12px;
                background: #1e2e1e; color: #a6e3a1; font-size: 13px;
            }
        """)
        self.build_btn.setEnabled(True)
        self.log(f"[*] Selected: {path}")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.accept()
        else: e.ignore()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(".apk"):
                self.set_apk(p); break

    def log(self, m):
        self.log_view.append(m)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start_build(self):
        if not self.apk_path: return
        for k, f in self.config_fields.items():
            self.config[k] = f.text().strip()
        self.build_btn.setEnabled(False)
        self.build_btn.setText("⏳  Building...")
        self.progress.setValue(0)
        self.log_view.clear()
        self.log("[*] Build started.")
        self.worker = BuildWorker(self.apk_path, self.config)
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.progress.setValue)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, ok, msg):
        self.build_btn.setEnabled(True)
        self.build_btn.setText("🚀  Start Build")
        box = DarkMessageBox("Success" if ok else "Error", msg)
        box.exec()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("MFF Auto-Modder") 
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())