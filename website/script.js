const year = document.getElementById('year');
if (year) year.textContent = new Date().getFullYear();

const track = document.getElementById('server-track');
if (track) {
  const names = [
    'Code Cave', 'Night Owls Hub', 'Pixel Arena', 'Study Circle', 'Meme Republic',
    'Build & Ship', 'Chill Gamers', 'Anime Corner', 'Music Lounge', 'AI Workshop',
    'Founders Den', 'Creators Guild', 'Dev School', 'Gen Z Spot', 'Server Lab'
  ];

  const html = [...names, ...names]
    .map((n) => `<span class="server-pill">${n} • Codunot online</span>`)
    .join('');

  track.innerHTML = html;
}
