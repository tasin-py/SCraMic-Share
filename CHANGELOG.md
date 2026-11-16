# What's new

Each release's notes on GitHub show its section from this file. Add one for every new version, headed `## x.y.z`.

## 1.2.9

- **Lighter:** the app sets aside about 370 MB less memory (on a 12-thread CPU; more on bigger CPUs) and runs 11 fewer threads. A math library it loads reserved 32 MB for each CPU thread, though the app never used it.
- **Updates:** Settings no longer flickers while an update downloads. This shows from the next update on, since the version doing the downloading is the one already installed.
- **Wireless:** fixes phones that couldn't open the link ("This site can't be reached", ERR_TOO_MANY_RETRIES) on PCs with VMware, Hyper-V, Docker or other server programs. Such a program could take the app's port, so phones reached it instead of SCraMic Share. Now the app keeps its ports to itself, and moves to a free port when one is taken. The QR code follows.
- **The app checks itself:** the Wireless screen now says what's wrong, and how to fix it, when:
  - another program answers on the app's port
  - a phone reached this PC but its connection kept failing
  - a phone opened the link with http:// instead of https://
  - no phone has reached this PC after a minute: same WiFi, guest WiFi and router isolation, mobile data, VPN
- **Error log:** Settings now has **Copy error log** and **Open log folder**. If something doesn't work, paste the log in a message to the developer. It notes app starts, ports, phones connecting, connection problems and errors. It never includes the phone link's key.

## 1.2.8

- **Wireless:** fixes phones that couldn't open the link ("This site can't be reached", ERR_TOO_MANY_RETRIES) on PCs with VMware, Hyper-V, Docker or other server programs. Such a program could take the app's port, so phones reached it instead of SCraMic Share. Now the app keeps its ports to itself, and moves to a free port when one is taken. The QR code follows.
- **The app checks itself:** the Wireless screen now says what's wrong, and how to fix it, when:
  - another program answers on the app's port
  - a phone reached this PC but its connection kept failing
  - a phone opened the link with http:// instead of https://
  - no phone has reached this PC after a minute: same WiFi, guest WiFi and router isolation, mobile data, VPN
- **Error log:** Settings now has **Copy error log** and **Open log folder**. If something doesn't work, paste the log in a message to the developer. It notes app starts, ports, phones connecting, connection problems and errors. It never includes the phone link's key.

## 1.2.7

- **iPhone battery:** the PC app now shows an iPhone's battery and whether it's charging, over WiFi too. iPhone browsers don't share the battery, so the app asks the iPhone through Apple's iPhone service (from the Apple Devices app or iTunes).
  - Click **Show Charge Percentage** next to the iPhone's name. A guide walks you through it and notices each step by itself: Apple's driver, the cable, then **Trust** on the iPhone. The app then turns on WiFi access on the iPhone, so you can unplug the cable. From then on the battery shows over WiFi, while the iPhone and PC are on the same WiFi.
- **Check the battery now:** a small battery button next to the battery level checks it right away, then every second for 15 seconds. Handy to see whether the phone started charging. Otherwise an iPhone's battery is checked every 20 seconds.
- **Battery while streaming:** the phone's battery now sits right next to the Resolution and FPS controls under the video.

## 1.2.6

- **Phone battery:** the PC app now shows your phone's battery level, and whether it's charging, next to the phone's name and under the video. This works on Android phones. iPhone browsers don't share the battery level, so it doesn't show for iPhones.
- **iPhone screen share:** if Bonjour isn't running, your iPhone can't find the PC in Screen Mirroring. The AirPlay screen now has a **Start Bonjour** button that starts it and sets it to start with Windows. Windows asks for permission.
- **iPhone screen share:** the AirPlay screen now also warns about antivirus firewalls (Avast and others) and shows how to fix them.

## 1.2.5

- **Wireless:** if something on the PC is likely to stop the phone from connecting, the Wireless screen now says so and shows how to fix it.
  - **Windows Firewall:** click **Allow through Windows Firewall**. Windows asks for permission.
  - **Antivirus firewalls** (Avast, AVG, Norton, Kaspersky, Bitdefender, ESET, McAfee and others): the screen shows where to set your network to Private, or how to allow SCraMic Share.

## 1.2.4

- **Wireless:** if the phone can't open the link, click **Doesn't open? Try another address** and pick another address. The QR code changes to it, so you can scan again.
- **Wireless:** addresses that a phone can never reach are no longer offered. These come from VMware, Hyper-V or a WiFi adapter that isn't connected.
- **Wireless:** the PC's address is looked up again each time you open Wireless, so the QR code stays right after the PC changes WiFi or gets a new address.
