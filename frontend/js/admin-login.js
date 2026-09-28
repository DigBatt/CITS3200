
function nextPath() {
  const next = new URLSearchParams(window.location.search).get('next');
  if (next && next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\')) {
    return next;
  }
  return '/admin';
}

function showLoginError(message) {
  const errorEl = document.getElementById('login-error');
  errorEl.textContent = message;
  errorEl.classList.add('visible');
}

async function attemptLogin() {
  const username = document.getElementById('login-username').value.trim();
  const passwordEl = document.getElementById('login-password');

  if (!username || !passwordEl.value) return;

  let res;
  try {
    res = await fetch('/api/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password: passwordEl.value }),
    });
  } catch {
    showLoginError('Could not reach the server. Is the backend running?');
    return;
  }

  if (res.ok) {
    window.location.href = nextPath();
    return;
  }

  const body = await res.json().catch(() => null);
  showLoginError(body?.error?.message ?? `Sign-in failed (${res.status}).`);
  passwordEl.value = '';
  passwordEl.focus();
}

document.getElementById('btn-login').addEventListener('click', attemptLogin);
['login-username', 'login-password'].forEach((id) => {
  document.getElementById(id).addEventListener('keydown', (e) => {
    if (e.key === 'Enter') attemptLogin();
  });
});
