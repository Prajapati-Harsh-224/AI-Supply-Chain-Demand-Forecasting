/* =========================================================
   DemandIQ — Admin Sidebar Toggle
   ========================================================= */

(function () {
  'use strict';

  const MOBILE_BP = 992; // px — matches the CSS breakpoint

  const backdrop = document.getElementById('sbBackdrop');

  /* ---------- helpers ---------- */
  function isMobile() {
    return window.innerWidth < MOBILE_BP;
  }

  function openSidebar() {
    document.body.classList.add('sb-open');
    if (backdrop) backdrop.style.display = 'block';
  }

  function closeSidebar() {
    document.body.classList.remove('sb-open');
    if (backdrop) backdrop.style.display = 'none';
  }

  function toggleDesktopCollapse() {
    document.body.classList.toggle('sb-hidden');
    // persist preference
    try {
      localStorage.setItem(
        'adminSidebarCollapsed',
        document.body.classList.contains('sb-hidden') ? '1' : '0'
      );
    } catch (e) { /* ignore */ }
  }

  /* ---------- main toggle ---------- */
  window.toggleSidebar = function () {
    if (isMobile()) {
      document.body.classList.contains('sb-open') ? closeSidebar() : openSidebar();
    } else {
      toggleDesktopCollapse();
    }
  };

  /* expose closeSidebar globally for backdrop onclick */
  window.closeSidebar = closeSidebar;

  /* ---------- close on backdrop click ---------- */
  if (backdrop) {
    backdrop.addEventListener('click', closeSidebar);
  }

  /* ---------- close with Escape key ---------- */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isMobile()) {
      closeSidebar();
    }
  });

  /* ---------- handle window resize ---------- */
  window.addEventListener('resize', function () {
    if (!isMobile()) {
      // on desktop, always hide backdrop and close mobile state
      closeSidebar();
    }
  });

  /* ---------- restore desktop collapse preference ---------- */
  (function restorePreference() {
    try {
      if (!isMobile() && localStorage.getItem('adminSidebarCollapsed') === '1') {
        document.body.classList.add('sb-hidden');
      }
    } catch (e) { /* ignore */ }
  }());

}());
