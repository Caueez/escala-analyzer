'use strict';
function csrfCookie() { return document.cookie.split('; ').find(item => item.startsWith('escala_csrf='))?.split('=')[1] || ''; }
async function identityRequest(path, options = {}) {
  const response = await fetch(path, {...options, credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfCookie(), ...(options.headers || {})}});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/auth/login') window.location.assign('/login');
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Confira os campos informados.');
  }
  return data;
}
function formData(form) { return Object.fromEntries(new FormData(form)); }
function formHandler(id, handler) {
  const form = document.getElementById(id);
  if (!form) return;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    document.getElementById('authError').textContent = '';
    try { await handler(formData(form)); form.reset(); }
    catch (error) { document.getElementById('authError').textContent = error.message; }
    finally { button.disabled = false; }
  });
}
formHandler('loginForm', async data => { await identityRequest('/api/auth/login', {method: 'POST', body: JSON.stringify(data)}); window.location.assign('/'); });
formHandler('passwordForm', async data => { await identityRequest('/api/auth/password', {method: 'POST', body: JSON.stringify(data)}); window.location.assign('/login'); });
formHandler('createUserForm', async data => { await identityRequest('/api/users', {method: 'POST', body: JSON.stringify(data)}); await loadUsers(); });
async function loadUsers() {
  const users = await identityRequest('/api/users');
  const list = document.getElementById('usersList'); list.replaceChildren();
  for (const user of users) {
    const row = document.createElement('div'); row.className = 'user-entry';
    const label = document.createElement('span'); label.textContent = `${user.name} · ${user.email} · ${user.role}${user.active ? '' : ' · inativo'}`;
    const button = document.createElement('button'); button.type = 'button'; button.className = 'button'; button.textContent = user.active ? 'Desativar' : 'Ativar';
    button.addEventListener('click', async () => { try { await identityRequest(`/api/users/${encodeURIComponent(user.id)}`, {method:'PATCH', body:JSON.stringify({role:user.role, active:!user.active})}); await loadUsers(); } catch(error) { document.getElementById('authError').textContent = error.message; } });
    row.append(label, button); list.append(row);
  }
}
if (document.getElementById('currentIdentity')) {
  identityRequest('/api/auth/me').then(async user => {
    document.getElementById('currentIdentity').textContent = `${user.name} · ${user.role}`;
    if (user.role === 'admin') { document.getElementById('userManagement').hidden = false; await loadUsers(); }
  }).catch(error => { document.getElementById('authError').textContent = error.message; });
  document.getElementById('logoutButton').addEventListener('click', async () => { await identityRequest('/api/auth/logout', {method:'POST'}); window.location.assign('/login'); });
}
