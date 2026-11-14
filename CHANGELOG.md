# What's new

Each release's notes on GitHub show its section from this file. Add one for every new version, headed `## x.y.z`.

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
