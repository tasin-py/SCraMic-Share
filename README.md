# SCraMic Share

Use your phone as a PC webcam, microphone, screen share, whiteboard and remote control, over WiFi or USB. For Windows, with iPhone and Android.

There's nothing to install on the phone: scan a QR code and it opens in the browser.

## Features

| Feature | What it does |
|---|---|
| **Camera share** | Your phone's camera on your PC |
| **Streamer mode** | Up to Full HD 60 fps (if the device camera allows), with resolution and FPS controls on the phone and PC |
| **Microphone** | Your phone's mic on your PC, with a mute button |
| **ScramicShare Cam / Mic** | Use the phone as a camera and microphone in Zoom, Meet, Discord, OBS and more |
| **Screen share** | Mirror your phone to the PC. On iPhone you can rotate the picture, and on Android you can make it share-only |
| **Teacher mode** | Draw on your PC screen from your phone |
| **PC Control** | Use your PC by touch, or watch only |

Camera and Streamer modes also have a dark screen option that saves battery, with a video on/off button.

## Install

1. Download `SCraMicShare-Setup-x.x.x.exe` from [Releases](https://github.com/tasin-py/SCraMic-Share/releases).
2. Run it. It installs just for you and doesn't need administrator rights.
3. **"Windows protected your PC"?** The app isn't code-signed yet, so this is expected for a new app. Click **More info**, then **Run anyway**. You can compare the file with the SHA-256 listed on the release first.

Needs Windows 10 or 11 (64-bit).

## Use it

### Wireless

1. Connect your phone and PC to the same WiFi.
2. Open SCraMic Share, click **Wireless**, and scan the QR code with your phone.
3. If the browser warns "Not private" or "Not secure", that's expected: the page comes from your own PC. Tap **Advanced → Proceed** (Android) or **Show Details → visit this website** (iPhone).
4. Pick a feature on your phone.

### Wired

Click **Wired** and follow the steps on screen.

- **Android:** needs USB debugging turned on.
- **iPhone:** works through Personal Hotspot over the cable. We recommend Wireless on iPhone, because it's much more stable.

### Screen share

- **iPhone:** open Control Center → Screen Mirroring → **SCraMicShare**. The first time, the app downloads a free AirPlay receiver.
- **Android over USB:** your screen opens on the PC by itself.
- **Android over WiFi (Android 11 or newer):** pair once using **Developer options → Wireless debugging → Pair device with pairing code**, and type the code and port into the PC. Older phones can use Windows' Wireless Display instead.

### ScramicShare Cam and Mic

In the app, open **Settings** and click **Install** next to each one. Windows asks for permission once. Then pick them in your other apps as the camera or microphone.

## Privacy and security

- **Your video and sound stay on your own network or cable.** There's no account and no cloud service.
- **Pairing:** the phone connects using a private key inside the QR code, so only share that code with devices you trust.
- **Update check:** each time it starts, the app asks GitHub for the list of releases. GitHub sees your internet address, as with any website. It never installs anything by itself.
- **Wireless debugging and USB debugging** let paired computers control your phone. Turn them off when you're on a network you don't trust.
- **Downloads:** some features download outside tools when first needed (listed below). The app only asks for them when you use that feature.

## Outside tools

These aren't part of this project. They're downloaded when needed, and they have their own licenses:

| Tool | Used for | License |
|---|---|---|
| [UxPlay for Windows](https://github.com/leapbtw/uxplay-windows) | iPhone screen share | GPL-3.0 |
| [scrcpy](https://github.com/Genymobile/scrcpy) | Android screen share | Apache-2.0 |
| [Android Platform-Tools](https://developer.android.com/tools/releases/platform-tools) | Android over USB and WiFi | Google's license |
| [UnityCapture](https://github.com/schellingb/UnityCapture) | ScramicShare Cam | MIT |
| [VB-CABLE](https://vb-audio.com/Cable/) | ScramicShare Mic | Donationware by VB-Audio |

## Run from source

Needs Python 3.10 or newer on Windows.

```bash
pip install -r requirements.txt
```

```bash
python scramicshare.py
```

## Support the project

Open **Settings → Buy me a Coffee** in the app, or use:

- **Bangla QR:** [web/assets/bangla-qr.png](web/assets/bangla-qr.png)
- **Binance ID:** 741109839

## License

SCraMic Share is licensed under the [Apache License 2.0](LICENSE). Teacher mode is based on [InkCast](https://github.com/ssfshad/inkcast) by ssfshad, also Apache-2.0. See [NOTICE](NOTICE) for details.

Made by Tasin's problem.
