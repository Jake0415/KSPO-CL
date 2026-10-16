'use client';

import { type FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useLogin } from '@/lib/session';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const router = useRouter();
  const login = useLogin();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await login.mutateAsync({ username, password });
      router.replace('/');
    } catch {
      setErr('아이디 또는 비밀번호가 올바르지 않습니다.');
    }
  }

  return (
    <div className="min-h-screen flex bg-bg">
      <div className="hidden md:flex w-1/2 bg-primary items-center justify-center">
        <div className="text-white">
          <div className="text-3xl font-bold">kspo-ingest</div>
          <div className="mt-2 text-sm opacity-80">운영 콘솔</div>
        </div>
      </div>
      <form onSubmit={submit} className="flex-1 flex items-center justify-center p-8">
        <div className="w-[360px] space-y-4">
          <h1 className="text-2xl font-semibold">로그인</h1>
          <Input
            label="아이디"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            autoFocus
            name="username"
          />
          <Input
            label="비밀번호"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            name="password"
          />
          {err && <div className="text-sm text-danger">{err}</div>}
          <Button type="submit" variant="primary" className="w-full" disabled={login.isPending}>
            {login.isPending ? '확인 중…' : '로그인'}
          </Button>
        </div>
      </form>
    </div>
  );
}
