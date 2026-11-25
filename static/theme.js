// Aplica o tema antes da renderização para evitar piscar o tema claro.
(function () {
  var theme = 'auto';
  try { theme = localStorage.getItem('prospecta-theme') || 'auto'; } catch (e) {}
  var dark = theme === 'dark' || (theme === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.classList.toggle('dark', dark);
  document.documentElement.dataset.theme = theme;
})();
