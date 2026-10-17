'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { supabase, configured } from '@/lib/supabase';

const TABS = [
  { href: '/', label: 'Today', icon: 'M4 5h16M4 12h16M4 19h10' },
  { href: '/desk/', label: 'Desk', icon: 'M5 4v16M12 4v16M19 4v16M3 8h4M10 14h4M17 10h4' },
  { href: '/alerts/', label: 'Alerts', icon: 'M12 4a5 5 0 0 0-5 5v4l-2 3h14l-2-3V9a5 5 0 0 0-5-5zM10 19a2 2 0 0 0 4 0' },
  { href: '/ledger/', label: 'Ledger', icon: 'M5 4h14v16H5zM8 9h8M8 13h8M8 17h5' },
  { href: '/edge/', label: 'Edge', icon: 'M4 18l5-6 4 3 7-9' },
];

function SignIn() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  // Email and password, no emailed link or code: works inside the home-screen app and needs no mail server.
  async function signIn(e) {
    e.preventDefault();
    setBusy(true); setMsg('');
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
    setBusy(false);
    if (error) setMsg('Email or password did not match. Check the user in Supabase under Authentication, Users.');
  }

  return (
    <main className="signin">
      <h1 className="wordmark">Halftime Desk</h1>
      <form onSubmit={signIn}>
        <label htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="username" inputMode="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="password">Password</label>
        <input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <button disabled={busy}>{busy ? 'Signing in' : 'Sign in'}</button>
      </form>
      {msg && <p className="err">{msg}</p>}
    </main>
  );
}

export default function Shell({ children }) {
  const path = usePathname();
  const [session, setSession] = useState(undefined);

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  if (!configured) return <main className="signin"><h1 className="wordmark">Halftime Desk</h1><p className="err">The app is missing its Supabase settings in Vercel.</p></main>;
  if (session === undefined) return <main className="signin" />;
  if (!session) return <SignIn />;

  return (
    <>
      <div className="screen">{children}</div>
      <nav className="tabbar" aria-label="Screens">
        {TABS.map((t) => {
          const on = t.href === '/' ? path === '/' : path.startsWith(t.href.replace(/\/$/, ''));
          return (
            <Link key={t.href} href={t.href} className={on ? 'tab on' : 'tab'} aria-current={on ? 'page' : undefined}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d={t.icon} /></svg>
              <span>{t.label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}
