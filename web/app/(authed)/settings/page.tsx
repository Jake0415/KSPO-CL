'use client';

import { type FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import { useChangePassword } from '@/api/settings';

export default function SettingsPage() {
  return (
    <AppShell title="설정" breadcrumbs={['홈', '설정']}>
      <div className="space-y-4 max-w-form">
        <PasswordTab />
      </div>
    </AppShell>
  );
}

function PasswordTab() {
  const router = useRouter();
  const { push } = useToast();
  const change = useChangePassword();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (next.length < 8) {
      setError('새 비밀번호는 8자 이상이어야 합니다.');
      return;
    }
    if (next !== confirm) {
      setError('새 비밀번호가 일치하지 않습니다.');
      return;
    }
    try {
      await change.mutateAsync({ current_password: current, new_password: next });
      push({ kind: 'success', msg: '비밀번호가 변경되었습니다 — 다시 로그인하세요' });
      router.replace('/login');
    } catch (err) {
      const msg = (err as Error).message;
      if (msg.includes('401')) {
        setError('현재 비밀번호가 올바르지 않습니다.');
      } else {
        setError('비밀번호 변경에 실패했습니다.');
      }
    }
  }

  return (
    <Card>
      <CardHeader
        title="비밀번호 변경"
        description="변경 후 모든 세션이 만료되며 새 비밀번호로 다시 로그인이 필요합니다."
      />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <Input
            type="password"
            label="현재 비밀번호"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            required
          />
          <Input
            type="password"
            label="새 비밀번호 (8자 이상)"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
            required
            minLength={8}
          />
          <Input
            type="password"
            label="새 비밀번호 확인"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            required
            minLength={8}
          />
          {error && <div className="text-sm text-danger">{error}</div>}
          <div className="flex justify-end">
            <Button type="submit" variant="primary" disabled={change.isPending}>
              {change.isPending ? '변경 중…' : '변경'}
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}
