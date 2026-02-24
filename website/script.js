const yearEl = document.getElementById('year');
if (yearEl) yearEl.textContent = new Date().getFullYear();

async function loadCommunities() {
  const track = document.getElementById('community-track');
  if (!track) return;

  try {
    const res = await fetch('communities.json', { cache: 'no-store' });
    if (!res.ok) throw new Error('Failed to load communities.json');
    const communities = await res.json();

    const cards = communities.map((c) => `
      <a class="community-card" href="${c.invite}" target="_blank" rel="noopener">
        <img src="${c.icon}" alt="${c.name} icon" />
        <div>
          <div class="community-name">${c.name}</div>
          <div class="community-members">${c.members}</div>
        </div>
      </a>
    `);

    track.innerHTML = [...cards, ...cards].join('');
  } catch {
    track.innerHTML = `
      <a class="community-card" href="https://discord.gg/GVuFk5gxtW" target="_blank" rel="noopener">
        <img src="https://cdn.top.gg/icons/799571124189618176/041c2d0d7f2919cb19e56f2e1f8a0d79e7dc9940f870adf07feab99dd3ce0a04.webp" alt="Codunot" />
        <div><div class="community-name">Official Codunot Server</div><div class="community-members">Tap to join</div></div>
      </a>
    `;
  }
}

loadCommunities();
