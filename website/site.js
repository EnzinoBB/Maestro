// Maestro site — tiny vanilla JS for tabs, copy buttons, theme toggle.
// No frameworks, no libs. Defer-loaded.

(function () {
  'use strict';

  // ─── Theme toggle ──────────────────────────────────────────
  const root = document.documentElement;
  const themeBtn = document.querySelector('.theme-toggle');
  const themeIcon = themeBtn && themeBtn.querySelector('.theme-icon');

  const stored = (() => {
    try { return localStorage.getItem('maestro-theme'); } catch (_) { return null; }
  })();
  if (stored === 'light' || stored === 'dark') {
    root.setAttribute('data-theme', stored);
  }
  function syncIcon() {
    if (!themeIcon) return;
    themeIcon.textContent = root.getAttribute('data-theme') === 'light' ? '☀' : '☾';
  }
  syncIcon();

  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('maestro-theme', next); } catch (_) {}
      syncIcon();
    });
  }

  // ─── Tabbed code blocks ────────────────────────────────────
  document.querySelectorAll('[data-tabs]').forEach((block) => {
    const tabs = block.querySelectorAll('.tab[data-tab]');
    const panes = block.querySelectorAll('[data-pane]');
    const copyBtn = block.querySelector('.copy[data-copy]');

    function activate(name) {
      tabs.forEach((t) => {
        const on = t.dataset.tab === name;
        t.classList.toggle('is-active', on);
        t.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      panes.forEach((p) => {
        const on = p.dataset.pane === name;
        p.hidden = !on;
      });
      if (copyBtn) copyBtn.dataset.copy = name;
    }

    tabs.forEach((tab) => {
      tab.addEventListener('click', () => activate(tab.dataset.tab));
    });
  });

  // ─── Copy buttons ──────────────────────────────────────────
  document.querySelectorAll('.copy').forEach((btn) => {
    btn.addEventListener('click', async () => {
      // Target: either the pane in this codeblock matching data-copy,
      // or the single <code data-raw-id> in this codeblock.
      const block = btn.closest('.codeblock');
      if (!block) return;

      let text = '';
      const key = btn.dataset.copy;
      if (key) {
        const byPane = block.querySelector(`[data-pane="${key}"] code`);
        const byId = block.querySelector(`[data-raw-id="${key}"]`);
        const target = byPane || byId;
        if (target) text = target.innerText;
      }
      if (!text) {
        const first = block.querySelector('.code code');
        if (first) text = first.innerText;
      }
      if (!text) return;

      try {
        await navigator.clipboard.writeText(text.trim());
        const prev = btn.textContent;
        btn.textContent = 'copied';
        btn.classList.add('is-copied');
        setTimeout(() => {
          btn.textContent = prev;
          btn.classList.remove('is-copied');
        }, 1400);
      } catch (_) {
        // fallback: select the text
        const range = document.createRange();
        range.selectNodeContents(block.querySelector('.code code'));
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
    });
  });
})();
