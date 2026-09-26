# iPhone Album Backup (Windows)

![Before / After](docs/images/before-after.png)

Left: what File Explorer shows when you open an iPhone. Photos are only grouped by
capture month. Right: what this tool produces. Your iPhone albums become folders.
Photos in no album go to `_Unsorted`; videos and screenshots go to `_MediaTypes`.
(The screenshot is from the Japanese UI.)

Backs up your iPhone photos and videos to a Windows PC **keeping your album and folder structure** —
the thing Windows Photos and Explorer cannot do. Works offline over USB. No cloud, no account.

- No freezes or "device unreachable" errors: it does not use the MTP path that Windows Photos uses
- Keeps your **Albums / Folders** exactly as on the iPhone, plus **Media Types** folders (Videos, Selfies, Live Photos, Screenshots, …)
- File names are prefixed with the capture date, so name order = shooting order
- Resumable: stop any time, unplug by accident, reboot — the next run continues where it left off
- Never deletes anything on the PC by itself. Optional "_Removed" folder mirrors deletions on the iPhone
- Originals are copied as-is (HEIC/MOV). The iPhone never has to transcode, so it does not overheat or drop the connection

```
E:\iPhoneAlbums\
 ├─ Family\
 │   └─ Sports day\     20240105_120000_IMG_0003.HEIC, 20240105_120000_IMG_0003.MOV ...
 ├─ Trip 2025\          20240106_103000_IMG_0001.HEIC ...
 ├─ _MediaTypes\        Videos / Selfies / Live Photos / … organized by year\year-month
 ├─ _Unsorted\          photos that are in no album, by year\year-month
 ├─ _Removed\           (optional) photos deleted or removed from albums on the iPhone
 ├─ _album_state.json   used to follow album renames — do not delete
 └─ _cache_DCIM\        the actual files — do not delete (album folders are hard links into it)
```

> **Tested on**: iPhone 11 Pro Max / iOS 26.6.1 / Windows 10 and 11 / genuine Apple USB cable / 84,000 items (207 GB).
> Other setups are untested. An iOS update may break it. No warranty — use at your own risk.

## Requirements
- Windows 10/11 with free space ≥ your library size + a little
- An **Apple original USB cable**. Testing is done with genuine cables only, so third-party cables are
  **not supported** — we cannot verify them all. In one case the iPhone was visible in File Explorer but
  this tool could not connect until a genuine cable was used. Charge-only cables never work.
- Apple's connection software, which provides the **Apple Mobile Device Service** this tool uses:
  **Apple Devices** from the Microsoft Store (Windows 11) or **iTunes** from apple.com (Windows 10).
  Open it once, confirm it detects your iPhone, then close it.
  > ⚠ Installing both iTunes and Apple Devices can conflict — keep only one, and restart the PC after switching.

## Installing (there is no installer)
Nothing to install — just extract and run.

1. **Right-click the zip → "Extract All"**.
   > ⚠ Do **not** double-click the exe from inside the zip preview. Windows would run it from a temporary
   > folder, and the album database (several GB) would have to be fetched again every time.
2. Move the extracted **`iPhoneAlbumBackup`** folder wherever you like — e.g. `D:\iPhoneAlbumBackup`.
   - The folder will hold the iPhone album database (**several GB**; ~7 GB for 84,000 items), so pick a drive with room.
   - Keeping it in Downloads works, but you will lose the database when you clean that folder out.
   - `C:\Program Files` works too (if the folder is not writable the app stores its data under your user profile), but it is not recommended.
   - You can move the whole folder to another drive later; it keeps working.

## How to use (exe)
1. Run `iPhoneAlbumBackup.exe`.
   If Windows shows "Windows protected your PC", click **More info → Run anyway** (unsigned indie software).
2. Switch **Language** to English in the top-right corner (remembered next time).
3. Connect the iPhone, unlock it, tap **Trust**. Keep it unlocked and connected during the backup.
4. The screen shows a device card, the 1/2/3 steps (the current one is highlighted; finished ones stay clickable so you can re-run them), a progress panel with counts/GB/percent/elapsed/remaining, and collapsible **Backup settings** (remembered between launches, except "skip downloading" which always resets) and **Details** (the log opens automatically on an error).
5. Press **1 Check connection** → **2 Review albums** (first time: 10–20 min to fetch album info) → choose **Save to** → **3 Start backup**.
6. It can take hours. Prevent the PC from sleeping. When finished, the destination folder opens automatically.

### Stopping / cable pulled / resuming
During a run button 3 becomes **■ Stop**. If the cable is pulled, a "Connection lost" window appears and the tool waits up to 10 minutes; plug it back in and it resumes by itself. Any later run resumes from where it stopped.

### Why is it slow? Will a faster PC help?
No. The iPhone's Lightning port is **USB 2.0**, so the PC, the destination drive and the cable cannot raise the
ceiling. Measured here: a single large file transfers at about **26 MB/s** (near the USB 2.0 limit), but tens of
thousands of small photos drop the effective rate to 9-12 MB/s because every file costs an open/read/close
round trip. Expect **4-5 hours for the first run** with 84,000 items / 170 GB; later runs only fetch what is new.

To speed it up: add the destination folder to **Windows Defender exclusions**, plug the cable into a port on the
PC itself (not a hub), leave the phone alone while it runs, and only tick "Refresh album info" when you actually
changed albums (it re-downloads several GB).

### Cloud-only photos
If "Optimize iPhone Storage" is on, some originals live only in iCloud. The tool lists them in `_cloud_only_photos.txt` before downloading. To fetch them, set Settings → Photos → **Download and Keep Originals** on the iPhone, wait, then run again.

### Before sharing logs
"Copy log" content can include the device name, album names, file names, and the destination
path — this may be personal information. Review it before posting in an Issue.

### The title bar says "Not Responding" / the window looks frozen

This shows up while the tool is listing the photos on the iPhone, where requests to
the device come in a tight stream. **The work is still running** — only the screen
stops updating.

**With a large library this lasts a while.** On a phone with 80,000 photos and 167 GB,
the window stayed frozen for up to **about 9 minutes**. It returns to normal at the
next step.

Do not force-quit it. Even if you do, downloaded files are kept and the next run
resumes from where it stopped.

### "Smart App Control blocked an app that might be unsafe"

This is a Windows 11 feature, usually on only after a clean install. It blocks any
app without a publisher signature. Unlike the "Windows protected your PC" warning,
there is **no "More info -> Run anyway"**, and you cannot allow a single app.

This tool is not code-signed, so the exe will not start while Smart App Control is on.
You have two options.

**1. Run from source instead (recommended)**

The zip contains a `source` folder with the full source code. With Python 3.12:

```
py -3.12 -m pip install pymobiledevice3==11.3.1 customtkinter==6.0.0
py -3.12 gui.py
```

No exe is involved, so nothing is blocked.

**2. Turn Smart App Control off**

Settings -> Privacy & security -> Windows Security ->
App & browser control -> Smart App Control settings -> Off

Recent Windows builds let you turn it back on afterwards, but not on every setup.
It disables a security feature, so the decision is yours.

### "Could not connect" even though File Explorer shows the iPhone
This is **not a cable problem**. Explorer uses MTP; this tool uses the same channel as iTunes, so one can
work while the other does not. Almost always the **Apple Mobile Device Service** is not running:
Win+R -> `services.msc` -> start **Apple Mobile Device Service** (Startup type: Automatic).
If it is not listed, install the **Apple Devices** app from the Microsoft Store and open it once.
Having both iTunes and Apple Devices installed can conflict — keep one and restart the PC.

### HEIC files will not open
Install "HEIF Image Extensions" from the Microsoft Store.

## Advanced (run from source)
```
py -3.12 -m pip install pymobiledevice3 customtkinter
py -3.12 gui.py                                   # GUI
py -3.12 album_export.py --lang en --out E:\iPhoneAlbums
```
Python 3.12 is required (3.13+ lacks Windows wheels for a dependency). `build.bat` builds the exe.

## Who built this

| Role | Work |
|---|---|
| XYZETON (author) | Concept, UI design, real-device testing, finding bugs, feature requests, release |
| Anthropic Claude | All of the implementation (database parsing, USB transfer, error handling, tests, build) |

The author is a graphic designer, not a programmer.

**Questions about usage, behaviour and bug reports are welcome. Questions about the
reasoning behind specific implementation choices may go unanswered.**
When reporting a problem, please include your iOS version, Windows version, whether
the cable is a genuine Apple one, and the log from the "Copy log" button.

## Supporting development

The tool is free. There is an optional way to support development, but **it changes
nothing about what you get** — no individual support, no warranty, no special build.
The link may move, so the current one is kept in this README.

[https://x.com/XYZETON］]

## Bundled source code

The tool is GPL-3.0, so the full source is included in the `source` folder of the zip.

```
source\
├ album_export.py  gui.py  probe.py  conftest.py  build.bat
└ tests\           (regression tests)
```

Run it from there if the exe is blocked on your machine (see above).

## Author & License
Author: **XYZETON**（X: @XYZETON）
GPL-3.0-or-later. See LICENSE and THIRD_PARTY_NOTICES.md. Developed with assistance from Anthropic Claude.
