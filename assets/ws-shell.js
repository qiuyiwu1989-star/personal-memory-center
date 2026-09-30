/* Standalone dashboard shell. Host integrations may replace this asset. */
(() => {
  const root = document.documentElement;
  const saved = localStorage.getItem('memory-theme');
  root.dataset.theme = saved === 'dark' || saved === 'light'
    ? saved : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = '切换深浅色';
  button.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('memory-theme', root.dataset.theme);
  });
  document.querySelector('main > header')?.append(button);
})();
