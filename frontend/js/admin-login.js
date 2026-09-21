// Administrator sign-in (S13).
//
// Posts the password to /api/admin/login. The endpoint does not exist yet,
// so the catch below reports that the backend is unreachable rather than
// letting anyone through.

async function attemptLogin() {
  const password = document.getElementById('login-password').value;
  const errorEl  = document.getElementById('login-error');

  if (!password) return;

  try {
    const res = await fetch('/api/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });

    if (res.ok) {
      sessionStorage.setItem('admin_session', '1');
      window.location.href = '/admin';
    } else {
      errorEl.classList.add('visible');
      document.getElementById('login-password').value = '';
      document.getElementById('login-password').focus();
    }
  } catch {
    // TODO: remove once S13 provides the endpoint.
    errorEl.textContent = 'Could not reach the server. Is the backend running?';
    errorEl.classList.add('visible');
  }
}

document.getElementById('btn-login').addEventListener('click', attemptLogin);
document.getElementById('login-password').addEventListener('keydown', e => {
  if (e.key === 'Enter') attemptLogin();
});