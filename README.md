# 🚀 MFF Auto-Modder

A fully automated, 1-click build pipeline for injecting a Native Mod Menu into **Marvel Future Fight (MFF)**. 

Instead of manually dumping `libil2cpp.so`, searching for RVAs, editing `Main.cpp`, and rebuilding via Gradle, this tool automates the entire process. Just drop the game's APK, click **Start Build**, and get a fully signed, modded APK.

---

## ✨ Features

- **1-Click Build Pipeline:** Extracts, dumps, patches, compiles, injects, and signs the APK automatically.
- **Dynamic RVA Resolver:** Uses `Il2CppDumper` to read `dump.cs` and automatically finds the exact memory offsets (RVAs) for the required hooks. No more manual updates when the game updates!
- **Strict Class Context Tracking:** Ensures the script grabs the correct function (e.g., `SkillManager.UseSkill` instead of `AI.UseSkill`).
- **Automated Native Build:** Triggers Gradle `clean`, `generateMenuDexDebug`, and `assembleDebug` to compile the `.so` file.
- **Auto-Injection & Signing:** Safely replaces the `assets/tphlib` inside the APK and signs it with v2 & v3 signatures.
- **Modern Cyberpunk UI:** A sleek PySide6 interface with a dark theme.

---

## 🛠️ Prerequisites

To use the source code or compile the `.exe` yourself, you need:
1. **Python 3.10+** installed on your PC.
2. **PySide6** (`pip install PySide6`).
3. **PyInstaller** (`pip install pyinstaller`) if you want to build the `.exe`.
4. **Il2CppDumper** (Included in the config paths).
5. **Android SDK & NDK** (For Gradle compilation).
6. A **Debug Keystore** (`debug.keystore`) to sign the final APK.

---

## 🚀 How to Use (For End Users)

1. Download the latest `MFF_Auto_Modder.exe` from the **Releases** tab.
2. Extract your clean, unmodified MFF APK (e.g., from APKPure).
3. Open the tool and **drag your clean APK** into the drop zone.
4. Verify the paths in the **Configuration** section (ensure they point to your local SDK, NDK, and `Main.cpp`).
5. Click **🚀 Start Build**.
6. Once finished, the modded APK will be saved in your output folder (default: `MODDED_TPH.apk`).
7. Install the APK on your rooted/emulated device.

---

## ⚙️ How it Works (Under the Hood)

The build pipeline follows these exact steps:

1. **Backup:** Copies your original APK to a `backups/` folder to prevent accidental overwrites.
2. **Extract:** Unzips `libil2cpp.so` and `global-metadata.dat` from the APK.
3. **Dump:** Runs `Il2CppDumper.exe` to generate a `dump.cs` file.
4. **Parse RVAs:** Scans the `dump.cs` line-by-line to find the correct RVAs for:
   - `AI::HitDamage_Internal` (Damage/God Mode)
   - `AI::GetSpeed` (Speed Multiplier)
   - `AI::IsMyPlayer` (Player check)
   - `ClickSkill::UpdateSkillCooltime` (UI Cooldown Spoof)
   - `SkillManager::UseSkill` (Engine Cooldown Spoof)
   - `SkillManager::IsCooltimeRunning` (Cooldown Check)
   - `SkillManager::IsCooltimeRunningWithSkillId` (Cooldown Check)
   - `SkillManager::SetSkillCoolTime` (Cooldown Timer)
5. **Patch:** Uses regex to replace the old RVAs inside `Main.cpp` with the freshly parsed ones.
6. **Compile:** Runs `gradlew clean`, `generateMenuDexDebug`, and `assembleDebug`.
7. **Inject:** Extracts the newly compiled `libShadow.so` from the Gradle build output and zips it into `assets/tphlib` inside the original APK.
8. **Sign:** Uses `apksigner` to sign the APK with v2 and v3 schemes, making it ready for installation.

---

## 📦 Building the EXE from Source

If you want to compile the Python script into a standalone `.exe`:

1. Clone this repository.
2. Open CMD in the project folder.
3. Run the PyInstaller command using the provided `.spec` file:
   ```cmd
   pyinstaller --noconfirm MFF_Auto_Modder.spec
   ```
4. Find your `.exe` inside the `dist/` folder. *(Note: The `.spec` file excludes heavy Qt modules, keeping the `.exe` under 45MB).*

---

## ⚠️ Disclaimer & Legal Notice

- **Educational Purposes Only:** This tool is developed for educational and research purposes. Modifying game files may violate Netmarble's Terms of Service.
- **Ban Risk:** Using mods in Marvel Future Fight can result in account bans. **Use a secondary account.**
- **No Liability:** The developer is not responsible for any account suspensions, data loss, or damages resulting from the use of this tool.
- **No Game Files:** This repository does **not** distribute the game's APK, `.so` files, or any copyrighted assets. You must provide your own clean APK.

---

## 🤝 Acknowledgments

- **Il2CppDumper:** Perfare / AndnixSH
- **LGL Mod Menu:** LGL Team
- **PySide6:** Qt for Python