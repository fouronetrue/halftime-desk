'use client';
import { createClient } from '@supabase/supabase-js';

// The publishable key is meant to ship to the browser. It reads nothing on its own: every table only answers
// a signed-in user, and sign-ups are off, so only accounts added by hand in the dashboard can get in.
const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

export const configured = Boolean(url && key);
export const supabase = configured
  ? createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true, storageKey: 'halftime-desk-auth' } })
  : null;
