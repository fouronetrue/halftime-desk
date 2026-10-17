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
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  async function send(e) {
    e.preventDefault();
    setBusy(true); setMsg('');
    const { error } = await supabase.auth.signInWithOtp({ email: email.trim(), options: { shouldCreateUser: false } });
    setBusy(false);
    if (error) setMsg(error.message.includes('Signups not allowed') ? 'That email has no account. Add it in Supabase first.' : error.message);
    else setSent(true);
  }
  async function verify(e) {
    e.preventDefault();
    setBusy(true); setMsg('');
    const { error } = await supabase.auth.verifyOtp({ email: email.trim(), token: code.trim(), type: 'email' });
    setBusy(false);
    if (error) setMsg('That code did not work. Codes expire after an hour; send a new one.');
  }

  return (
    <main className="signin">
      <h1 className="wordmark">Halftime Desk</h1>
      {!sent ? (
        <form onSubmit={send}>
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="email" inputMode="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <button disabled={busy}>{busy ? 'Sending' : 'Email me a code'}</button>
        </form>
      ) : (
        <form onSubmit={verify}>
          <label htmlFor="code">Code from the email to {email}</label>
          <input id="code" inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} />
          <button disabled={busy}>{busy ? 'Checking' : 'Sign in'}</button>
          <button type="button" className="link" onClick={() => { setSent(false); setCode(''); }}>Use a different email</button>
        </form>
      )}
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
