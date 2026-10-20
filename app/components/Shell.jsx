'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { supabase, configured } from '@/lib/supabase';

// Today opens a game's Desk by tapping its card; the Desk and the Ledger are reachable by URL, not from here.
const TABS = [
  { href: '/', label: 'Today', icon: 'M4 5h16M4 12h16M4 19h10' },
  { href: '/bets/', label: 'Bets', icon: 'M4 7h16v4a2 2 0 0 0 0 4v4H4v-4a2 2 0 0 0 0-4zM14 7v12' },
  { href: '/alerts/', label: 'Alerts', icon: 'M12 4a5 5 0 0 0-5 5v4l-2 3h14l-2-3V9a5 5 0 0 0-5-5zM10 19a2 2 0 0 0 4 0' },
  { href: '/calc/', label: 'Calc', icon: 'M6 3h12v18H6zM9 7h6M9 11h2M13 11h2M9 15h2M13 15h2' },
  { href: '/record/', label: 'Record', icon: 'M4 18l5-6 4 3 7-9M16 6h4v4' },
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
