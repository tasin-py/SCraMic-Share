// Line icons shared by the PC app and the phone site. icon('mic') -> '<svg ...>'
const ICONS = {
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 11l5-3v8l-5-3"/>',
  videoOff: '<path d="M8 6h6a2 2 0 0 1 2 2v3l5-3v8l-2-1.2M16 16a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2"/><path d="M3 3l18 18"/>',
  streamer: '<rect x="3" y="7" width="13" height="10" rx="2"/><path d="M16 11l5-3v8l-5-3"/><path d="M7 4h5M9.5 4v3"/>',
  wifi: '<path d="M2 8.8a15 15 0 0 1 20 0"/><path d="M5 12.4a10 10 0 0 1 14 0"/><path d="M8.5 15.9a5 5 0 0 1 7 0"/><circle cx="12" cy="19.4" r="1.1" fill="currentColor" stroke="none"/>',
  wire: '<path d="M9 2v4M15 2v4"/><rect x="6" y="6" width="12" height="8" rx="2"/><path d="M12 14v3a3 3 0 0 0 3 3h3a2 2 0 0 1 2 2"/>',
  camera: '<path d="M3 8.5A2.5 2.5 0 0 1 5.5 6H7l1.6-2.2h6.8L17 6h1.5A2.5 2.5 0 0 1 21 8.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/><circle cx="12" cy="12.8" r="3.6"/>',
  screen: '<rect x="6.5" y="2" width="11" height="20" rx="2.6"/><path d="M10.5 18.5h3"/><path d="M1.5 9.5a6 6 0 0 1 2.5 2.5M1.5 6a10 10 0 0 1 3.8 3.8"/>',
  mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v4"/>',
  micOff: '<path d="M15 9.3V5a3 3 0 0 0-5.7-1.3"/><path d="M9 9v2a3 3 0 0 0 5 2.2"/><path d="M19 11a7 7 0 0 1-1.2 3.9M5 11a7 7 0 0 0 11.5 5.4"/><path d="M12 18v4"/><path d="M3 3l18 18"/>',
  teacher: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21l4-4 4 4"/><path d="M6.5 12.5l3-3 2.5 2 5-5"/>',
  pcControl: '<rect x="2" y="3" width="20" height="13" rx="2"/><path d="M8 21h8M12 16v5"/><path d="M10 6.2l5.4 3.8-2.4.6 1.4 2.6-1.3.7-1.4-2.6-1.7 1.7z" fill="currentColor" stroke-width="1"/>',
  switchCam: '<path d="M20 11a8 8 0 0 0-14.6-4.5M4 3.5V7h3.5"/><path d="M4 13a8 8 0 0 0 14.6 4.5M20 20.5V17h-3.5"/><circle cx="12" cy="12" r="2.4"/>',
  rotate: '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.5 3.5v5h-5"/>',
  moon: '<path d="M20.5 13.2A8.6 8.6 0 1 1 10.8 3.5a6.7 6.7 0 0 0 9.7 9.7z"/>',
  record: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5" fill="currentColor"/>',
  popOut: '<path d="M14 4h6v6"/><path d="M20 4l-8 8"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
  power: '<path d="M12 2.5v9"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>',
  settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  back: '<path d="M15 18l-6-6 6-6"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  coffee: '<path d="M3.5 9h13.5v4.5a6 6 0 0 1-6 6h-1.5a6 6 0 0 1-6-6z"/><path d="M17 11h1.3a2.6 2.6 0 0 1 0 5.2H17"/><path d="M7.5 2.5v3.5M11.5 2.5v3.5"/>',
  facebook: '<rect x="3" y="3" width="18" height="18" rx="5"/><path d="M15.2 7.6h-1.6a2.6 2.6 0 0 0-2.6 2.6V21M8.6 12.6h6.2"/>',
  instagram: '<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.3" cy="6.7" r="1.1" fill="currentColor" stroke="none"/>',
  github: '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.4 5.4 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/>',
  arrowOut: '<path d="M7 17L17 7M9 7h8v8"/>',
  phone: '<rect x="6.5" y="2" width="11" height="20" rx="2.6"/><path d="M10.5 18.5h3"/>',
};

function icon(name, cls) {
  return `<svg class="ic ${cls || ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
}

// <i data-ic="mic"></i>  ->  inline svg
function hydrateIcons(root) {
  (root || document).querySelectorAll('[data-ic]').forEach(el => {
    el.innerHTML = icon(el.dataset.ic);
    el.removeAttribute('data-ic');
  });
}
