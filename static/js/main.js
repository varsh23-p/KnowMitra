/**
 * KnowMitra – main.js  v2
 * Handles: sidebar, dropdowns, modals, tabs, toasts, animations,
 *          password toggle, char counter, skill autocomplete, star rating,
 *          scroll effects, chat polling, confirm dialogs.
 */

/* ═══════════════════════════════════════════════════════════════
   1. DOM-ready bootstrap
═══════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  initDropdowns();
  initModals();
  initTabs();
  initAlerts();
  initPasswordToggles();
  initCharCounters();
  initConfirmButtons();
  initActiveNavLinks();
  initSkillAutocomplete();
  initStarRatings();
  initScrollEffects();
  initFormValidation();
  initAvatarFallbacks();
  renderFlashToasts();
  animateCounters();
});

/* ═══════════════════════════════════════════════════════════════
   2. Sidebar
═══════════════════════════════════════════════════════════════ */
function initSidebar() {
  const sidebar  = document.getElementById('sidebar');
  const overlay  = document.getElementById('sidebarOverlay');
  const openers  = document.querySelectorAll('.hamburger-btn, .hamburger-landing-btn');

  if (!sidebar) return;

  const open  = () => { sidebar.classList.add('open'); overlay?.classList.add('visible'); document.body.style.overflow = 'hidden'; };
  const close = () => { sidebar.classList.remove('open'); overlay?.classList.remove('visible'); document.body.style.overflow = ''; };

  openers.forEach(btn => btn.addEventListener('click', () =>
    sidebar.classList.contains('open') ? close() : open()
  ));

  overlay?.addEventListener('click', close);

  // Close on escape
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
}

/* ═══════════════════════════════════════════════════════════════
   3. Dropdowns
═══════════════════════════════════════════════════════════════ */
function initDropdowns() {
  document.querySelectorAll('[data-dropdown]').forEach(trigger => {
    const menuId = trigger.dataset.dropdown;
    const menu   = document.getElementById(menuId);
    if (!menu) return;

    trigger.addEventListener('click', e => {
      e.stopPropagation();
      const isOpen = menu.classList.contains('open');
      // Close all open dropdowns first
      document.querySelectorAll('.dropdown-menu.open').forEach(m => m.classList.remove('open'));
      if (!isOpen) menu.classList.add('open');
    });
  });

  document.addEventListener('click', () =>
    document.querySelectorAll('.dropdown-menu.open').forEach(m => m.classList.remove('open'))
  );
}

/* ═══════════════════════════════════════════════════════════════
   4. Modals
═══════════════════════════════════════════════════════════════ */
function initModals() {
  // Open
  document.querySelectorAll('[data-modal-open]').forEach(btn => {
    btn.addEventListener('click', () => openModal(btn.dataset.modalOpen));
  });

  // Close via close button or overlay click
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) closeModal(overlay.id);
    });
    const closeBtn = overlay.querySelector('.modal-close');
    closeBtn?.addEventListener('click', () => closeModal(overlay.id));
  });

  // Close via [data-modal-close]
  document.querySelectorAll('[data-modal-close]').forEach(btn => {
    btn.addEventListener('click', () => {
      const overlay = btn.closest('.modal-overlay');
      if (overlay) closeModal(overlay.id);
    });
  });

  // ESC key
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal-overlay.open').forEach(o => closeModal(o.id));
    }
  });
}

function openModal(id) {
  const el = document.getElementById(id);
  if (el) { el.classList.add('open'); document.body.style.overflow = 'hidden'; }
}
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) { el.classList.remove('open'); document.body.style.overflow = ''; }
}
// Expose globally
window.openModal  = openModal;
window.closeModal = closeModal;

/* ═══════════════════════════════════════════════════════════════
   5. Tabs
═══════════════════════════════════════════════════════════════ */
function initTabs() {
  document.querySelectorAll('[data-tabs]').forEach(container => {
    const tabs  = container.querySelectorAll('[data-tab]');
    const panes = container.querySelectorAll('[data-tab-pane]');

    const activate = (tabId) => {
      tabs.forEach(t  => t.classList.toggle('active', t.dataset.tab === tabId));
      panes.forEach(p => p.classList.toggle('active', p.dataset.tabPane === tabId));
    };

    tabs.forEach(tab => {
      tab.addEventListener('click', e => {
        e.preventDefault();
        activate(tab.dataset.tab);
        // Update URL hash without scroll
        history.replaceState(null, '', '#' + tab.dataset.tab);
      });
    });

    // Activate from URL hash or first tab
    const hash = location.hash.replace('#', '');
    const match = [...tabs].find(t => t.dataset.tab === hash);
    if (match) activate(hash);
    else if (tabs.length) activate(tabs[0].dataset.tab);
  });
}

/* ═══════════════════════════════════════════════════════════════
   6. Auto-dismiss flash alerts
═══════════════════════════════════════════════════════════════ */
function initAlerts() {
  document.querySelectorAll('.alert').forEach(alert => {
    const closeBtn = alert.querySelector('.alert-close');
    closeBtn?.addEventListener('click', () => dismissAlert(alert));
    setTimeout(() => dismissAlert(alert), 6000);
  });
}
function dismissAlert(el) {
  el.style.transition = 'opacity .3s ease, transform .3s ease, margin .3s ease, padding .3s ease, height .3s ease';
  el.style.opacity = '0';
  el.style.transform = 'translateY(-6px)';
  setTimeout(() => el.remove(), 300);
}

/* ═══════════════════════════════════════════════════════════════
   7. Toast notifications
═══════════════════════════════════════════════════════════════ */
function getToastContainer() {
  let c = document.getElementById('toast-container');
  if (!c) {
    c = document.createElement('div');
    c.id = 'toast-container';
    document.body.appendChild(c);
  }
  return c;
}

function showToast(message, type = 'info', duration = 4500) {
  const icons = {
    success: 'fa-check-circle',
    danger:  'fa-times-circle',
    warning: 'fa-exclamation-triangle',
    info:    'fa-info-circle',
  };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <i class="fas ${icons[type] || icons.info} toast-icon"></i>
    <span class="toast-msg">${message}</span>
    <button class="toast-close" onclick="removeToast(this.closest('.toast'))">
      <i class="fas fa-times"></i>
    </button>`;
  getToastContainer().appendChild(toast);
  setTimeout(() => removeToast(toast), duration);
}
function removeToast(el) {
  if (!el) return;
  el.classList.add('removing');
  setTimeout(() => el.remove(), 260);
}
window.showToast   = showToast;
window.removeToast = removeToast;

/* Convert server-side flash messages to toasts if #flash-data element exists */
function renderFlashToasts() {
  const el = document.getElementById('flash-data');
  if (!el) return;
  try {
    const flashes = JSON.parse(el.textContent);
    flashes.forEach(([cat, msg]) => showToast(msg, cat === 'error' ? 'danger' : cat));
  } catch(e) {}
}

/* ═══════════════════════════════════════════════════════════════
   8. Password toggle
═══════════════════════════════════════════════════════════════ */
function initPasswordToggles() {
  document.querySelectorAll('.pw-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = btn.closest('.pw-wrap')?.querySelector('input');
      if (!input) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      const icon = btn.querySelector('i');
      if (icon) { icon.classList.toggle('fa-eye', !show); icon.classList.toggle('fa-eye-slash', show); }
    });
  });
}

/* ═══════════════════════════════════════════════════════════════
   9. Character counters
═══════════════════════════════════════════════════════════════ */
function initCharCounters() {
  document.querySelectorAll('[data-maxlength]').forEach(el => {
    const max     = parseInt(el.dataset.maxlength);
    const targetId = el.dataset.countTarget;
    const counter  = targetId ? document.getElementById(targetId) : el.nextElementSibling;
    const update   = () => {
      const left = max - el.value.length;
      if (counter) counter.textContent = `${left} characters remaining`;
      if (left < 0) { el.classList.add('error'); counter?.classList.add('text-danger'); }
      else          { el.classList.remove('error'); counter?.classList.remove('text-danger'); }
    };
    el.addEventListener('input', update);
    update();
  });
}

/* ═══════════════════════════════════════════════════════════════
   10. Confirm before action
═══════════════════════════════════════════════════════════════ */
function initConfirmButtons() {
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', e => {
      if (!confirm(el.dataset.confirm)) e.preventDefault();
    });
  });
}

/* ═══════════════════════════════════════════════════════════════
   11. Active nav item (based on URL)
═══════════════════════════════════════════════════════════════ */
function initActiveNavLinks() {
  const path = window.location.pathname;
  document.querySelectorAll('.nav-item[href]').forEach(link => {
    const href = link.getAttribute('href');
    if (href && href !== '/' && path.startsWith(href)) {
      link.classList.add('active');
    } else if (href === '/' && path === '/') {
      link.classList.add('active');
    }
  });
}

/* ═══════════════════════════════════════════════════════════════
   12. Skill autocomplete search
═══════════════════════════════════════════════════════════════ */
function initSkillAutocomplete() {
  const input   = document.getElementById('skillSearchInput');
  const results = document.getElementById('skillSearchResults');
  const idField = document.getElementById('skillIdHidden');
  if (!input || !results) return;

  let debounceTimer;
  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (q.length < 2) { results.innerHTML = ''; results.classList.add('hidden'); return; }
    debounceTimer = setTimeout(async () => {
      try {
        const res  = await fetch(`/skills/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        if (!data.length) {
          results.innerHTML = '<div class="skill-suggest-empty">No results found</div>';
        } else {
          results.innerHTML = data.map(s =>
            `<div class="skill-suggest-item" data-id="${s.id}" data-name="${s.name}" tabindex="0">
               <i class="fas fa-tag"></i>
               <span class="suggest-name">${s.name}</span>
               <span class="suggest-cat">${s.category}</span>
             </div>`
          ).join('');
        }
        results.classList.remove('hidden');
      } catch (e) { console.error(e); }
    }, 280);
  });

  results.addEventListener('click', e => {
    const item = e.target.closest('[data-id]');
    if (!item) return;
    input.value = item.dataset.name;
    if (idField) idField.value = item.dataset.id;
    results.classList.add('hidden');
    results.innerHTML = '';
    input.focus();
  });

  document.addEventListener('click', e => {
    if (!input.contains(e.target) && !results.contains(e.target)) {
      results.classList.add('hidden');
    }
  });

  // Keyboard navigation in results
  input.addEventListener('keydown', e => {
    const items = [...results.querySelectorAll('[data-id]')];
    if (!items.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); items[0].focus(); }
  });
  results.addEventListener('keydown', e => {
    const items   = [...results.querySelectorAll('[data-id]')];
    const current = document.activeElement;
    const idx     = items.indexOf(current);
    if (e.key === 'ArrowDown') { e.preventDefault(); items[idx + 1]?.focus(); }
    if (e.key === 'ArrowUp')   { e.preventDefault(); idx > 0 ? items[idx - 1].focus() : input.focus(); }
    if (e.key === 'Enter' && idx >= 0) { e.preventDefault(); current.click(); }
    if (e.key === 'Escape')    { results.classList.add('hidden'); input.focus(); }
  });
}

/* ═══════════════════════════════════════════════════════════════
   13. Star rating inputs
═══════════════════════════════════════════════════════════════ */
function initStarRatings() {
  document.querySelectorAll('.star-rating-input').forEach(group => {
    const hidden = document.getElementById(group.dataset.target || '');
    group.querySelectorAll('input').forEach(input => {
      input.addEventListener('change', () => {
        if (hidden) hidden.value = input.value;
      });
    });
  });
}

/* ═══════════════════════════════════════════════════════════════
   14. Scroll effects (navbar + fade-in elements)
═══════════════════════════════════════════════════════════════ */
function initScrollEffects() {
  // Landing navbar scroll state
  const nav = document.querySelector('.landing-nav');
  if (nav) {
    const update = () => nav.classList.toggle('scrolled', window.scrollY > 50);
    window.addEventListener('scroll', update, { passive: true });
    update();
  }

  // Intersection observer for fade-in-up elements
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });

  document.querySelectorAll('.fade-in-up').forEach(el => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(24px)';
    el.style.transition = 'opacity .5s ease, transform .5s ease';
    observer.observe(el);
  });

  // Add visible style
  document.head.insertAdjacentHTML('beforeend',
    '<style>.fade-in-up.visible{opacity:1!important;transform:translateY(0)!important;}</style>'
  );
}

/* ═══════════════════════════════════════════════════════════════
   15. Counter animation (stat numbers)
═══════════════════════════════════════════════════════════════ */
function animateCounters() {
  const counters = document.querySelectorAll('[data-count]');
  if (!counters.length) return;

  const obs = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const el    = entry.target;
      const end   = parseFloat(el.dataset.count);
      const dur   = 1400;
      const steps = 60;
      const inc   = end / steps;
      let   cur   = 0;
      const isInt = Number.isInteger(end);
      const timer = setInterval(() => {
        cur += inc;
        if (cur >= end) { cur = end; clearInterval(timer); }
        el.textContent = isInt ? Math.floor(cur) : cur.toFixed(1);
      }, dur / steps);
      obs.unobserve(el);
    });
  }, { threshold: 0.5 });

  counters.forEach(el => obs.observe(el));
}

/* ═══════════════════════════════════════════════════════════════
   16. Form validation helpers
═══════════════════════════════════════════════════════════════ */
function initFormValidation() {
  // Live email validation
  document.querySelectorAll('input[type="email"]').forEach(input => {
    input.addEventListener('blur', () => {
      const valid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.value);
      input.classList.toggle('error',   input.value && !valid);
      input.classList.toggle('success', input.value &&  valid);
    });
  });

  // Password strength indicator
  document.querySelectorAll('[data-pw-strength]').forEach(input => {
    const barId = input.dataset.pwStrength;
    const bar   = document.getElementById(barId);
    if (!bar) return;
    input.addEventListener('input', () => {
      const score = getPasswordStrength(input.value);
      const colors = ['#ef4444', '#f59e0b', '#3b82f6', '#10b981'];
      const labels = ['Weak', 'Fair', 'Good', 'Strong'];
      bar.style.width  = `${(score + 1) * 25}%`;
      bar.style.background = colors[score];
      const label = bar.closest('.pw-strength-wrap')?.querySelector('.pw-strength-label');
      if (label) { label.textContent = labels[score]; label.style.color = colors[score]; }
    });
  });
}

function getPasswordStrength(pw) {
  let score = 0;
  if (pw.length >= 6)  score++;
  if (pw.length >= 10) score++;
  if (/[A-Z]/.test(pw) && /[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  return Math.min(score, 3);
}

/* ═══════════════════════════════════════════════════════════════
   17. Avatar fallback (broken images)
═══════════════════════════════════════════════════════════════ */
function initAvatarFallbacks() {
  document.querySelectorAll('img.avatar').forEach(img => {
    img.addEventListener('error', () => {
      const initials = img.dataset.initials || '?';
      const placeholder = document.createElement('div');
      placeholder.className = img.className.replace('avatar', 'avatar avatar-placeholder');
      placeholder.style.cssText = img.style.cssText;
      placeholder.textContent = initials;
      img.parentNode?.replaceChild(placeholder, img);
    });
  });
}

/* ═══════════════════════════════════════════════════════════════
   18. Chat message polling (conversation page)
═══════════════════════════════════════════════════════════════ */
function initChatPolling(partnerId, currentUserId) {
  const chatWin = document.getElementById('chatMessages');
  if (!chatWin) return;

  let lastId = Math.max(
    0, ...[...chatWin.querySelectorAll('[data-msg-id]')].map(el => parseInt(el.dataset.msgId) || 0)
  );

  function appendMessage(m) {
    const row = document.createElement('div');
    row.className = `msg-row ${m.is_mine ? 'mine' : 'theirs'}`;
    row.dataset.msgId = m.id;
    row.innerHTML = `
      ${!m.is_mine ? `<div class="avatar-placeholder avatar-xs" style="font-size:.6rem;flex-shrink:0;">${m.sender_name[0].toUpperCase()}</div>` : ''}
      <div>
        <div class="msg-bubble ${m.is_mine ? 'mine' : 'theirs'}">${escapeHtml(m.content)}</div>
        <div class="msg-time">${m.created_at}</div>
      </div>`;
    chatWin.appendChild(row);
    lastId = Math.max(lastId, m.id);
    chatWin.scrollTop = chatWin.scrollHeight;
  }

  async function poll() {
    try {
      const res  = await fetch(`/messages/poll/${partnerId}?since=${lastId}`);
      const msgs = await res.json();
      msgs.forEach(appendMessage);
    } catch(e) {}
  }

  // Scroll to bottom initially
  chatWin.scrollTop = chatWin.scrollHeight;

  // Poll every 4s
  setInterval(poll, 4000);

  // Enter to send
  const textarea = document.getElementById('chatTextarea');
  textarea?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      textarea.closest('form')?.submit();
    }
  });

  // Auto-resize textarea
  textarea?.addEventListener('input', () => {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
  });
}
window.initChatPolling = initChatPolling;

/* ═══════════════════════════════════════════════════════════════
   19. Skill tag management (My Skills page)
═══════════════════════════════════════════════════════════════ */
function initSkillTagRemove() {
  document.querySelectorAll('.skill-tag.removable').forEach(tag => {
    tag.addEventListener('click', () => {
      const form = tag.querySelector('form') || tag.closest('[data-remove-form]');
      if (form) form.submit();
    });
  });
}
window.initSkillTagRemove = initSkillTagRemove;

/* ═══════════════════════════════════════════════════════════════
   20. Category pill filter (discovery page)
═══════════════════════════════════════════════════════════════ */
function initCategoryFilter() {
  document.querySelectorAll('.category-pill[data-filter]').forEach(pill => {
    pill.addEventListener('click', () => {
      document.querySelectorAll('.category-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      const cat = pill.dataset.filter;
      document.querySelectorAll('[data-card-category]').forEach(card => {
        card.closest('.student-card-wrap')?.classList.toggle('hidden', cat !== 'all' && card.dataset.cardCategory !== cat);
      });
    });
  });
}
window.initCategoryFilter = initCategoryFilter;

/* ═══════════════════════════════════════════════════════════════
   21. Smooth scroll-to-top button
═══════════════════════════════════════════════════════════════ */
(function initScrollTop() {
  const btn = document.getElementById('scrollTopBtn');
  if (!btn) return;
  window.addEventListener('scroll', () => btn.classList.toggle('visible', window.scrollY > 400), { passive: true });
  btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
})();

/* ═══════════════════════════════════════════════════════════════
   22. Utility helpers
═══════════════════════════════════════════════════════════════ */
function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
