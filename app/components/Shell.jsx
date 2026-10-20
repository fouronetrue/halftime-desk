'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { supabase, configured } from '@/lib/supabase';
import { shellHeight } from '@/lib/desk';

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
  const screen = useRef(null);
  const [debug, setDebug] = useState('');

  // The screen is the scroll container, so a new tab starts at the top. And when an input gives up focus (the
  // keyboard closes), put the window back where it belongs: iOS can leave it nudged after a keyboard on a page
  // too short to scroll, which is what moved the tab bar around.
  useEffect(() => { screen.current?.scrollTo(0, 0); }, [path]);
  useEffect(() => {
    const settle = () => setTimeout(() => window.scrollTo(0, 0), 60);
    document.addEventListener('focusout', settle);
    return () => document.removeEventListener('focusout', settle);
  }, []);

  // The shell is sized to what is actually visible. In the home-screen app iOS lays the page out short by the
  // status bar (innerHeight, 100dvh and the visual viewport all read screen minus status bar) while the web view
  // fills the screen and only 100lvh says so; shellHeight() adds that back. Under the keyboard the visible area
  // shrinks and the bar steps aside. ?debug in the URL, or five quick taps on the Watching line on Today, show
  // the numbers and draw a line where the browser puts the bottom of the page.
  useEffect(() => {
    const vv = window.visualViewport;
    const root = document.documentElement;
    const standalone = window.navigator.standalone === true;
    let wantDebug = /[?&]debug/.test(window.location.search);
    const measure = (css) => { const d = document.createElement('div'); d.style.cssText = `position:fixed;left:0;width:0;visibility:hidden;${css}`; document.body.appendChild(d); const r = d.getBoundingClientRect(); d.remove(); return r; };
    const apply = () => {
      const vis = vv ? vv.height : window.innerHeight;
      const t = vv ? vv.offsetTop : 0;
      const kb = vis < window.innerHeight * 0.75;
      const large = measure('top:0;height:100lvh').height;
      const full = shellHeight({ vis, inner: window.innerHeight, large, standalone });
      root.style.setProperty('--vvh', `${full}px`);
      root.style.setProperty('--vvt', `${Math.round(t)}px`);
      root.classList.toggle('kb', kb);
      if (!kb && window.scrollY) window.scrollTo(0, 0);   // iOS nudges the window after a keyboard; put it back
      if (wantDebug) {
        const sh = document.querySelector('.shell'), bar = document.querySelector('.tabbar');
        const r = sh ? sh.getBoundingClientRect() : null, br = bar ? bar.getBoundingClientRect() : null;
        const insetTop = measure('top:env(safe-area-inset-top);height:0').top;
        const insetBottom = window.innerHeight - measure('bottom:env(safe-area-inset-bottom);height:0').bottom;
        const units = ['dvh', 'svh', 'lvh'].map((u) => `${u} ${Math.round(measure(`top:0;height:100${u}`).height)}`).join(' ');
        setDebug(`standalone ${standalone} screen ${window.screen.width}x${window.screen.height} inner ${window.innerWidth}x${window.innerHeight} ` +
                 `vv ${Math.round(vv?.width || 0)}x${Math.round(vis)} top ${Math.round(t)} client ${root.clientHeight} ${units} inset ${Math.round(insetTop)}/${Math.round(insetBottom)} ` +
                 `shell ${full} drawn ${r ? `${Math.round(r.top)}+${Math.round(r.height)}` : '?'} bar ${br ? `${Math.round(br.top)}-${Math.round(br.bottom)}` : '?'} scrollY ${window.scrollY}`);
      }
    };
    const toggle = () => { wantDebug = !wantDebug; if (!wantDebug) setDebug(''); apply(); };
    apply();
    vv?.addEventListener('resize', apply);
    vv?.addEventListener('scroll', apply);
    window.addEventListener('resize', apply);
    window.addEventListener('orientationchange', apply);
    window.addEventListener('hd-debug', toggle);
    return () => {
      vv?.removeEventListener('resize', apply);
      vv?.removeEventListener('scroll', apply);
      window.removeEventListener('resize', apply);
      window.removeEventListener('orientationchange', apply);
      window.removeEventListener('hd-debug', toggle);
    };
  }, []);

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
    <div className="shell">
      {debug && <><pre className="vpdebug">{debug}</pre><div className="vpline" aria-hidden="true" /></>}
      <div className="screen" ref={screen}>{children}</div>
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
    </div>
  );
}
