'use client';

import { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Button } from './Button';
import { Input } from './Input';

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  confirmText?: string;
  cancelText?: string;
  /** 입력 일치 검증을 강제할 문자열 (예: 호스트명) */
  requireMatch?: string;
  onConfirm: () => void;
};

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmText = '삭제',
  cancelText = '취소',
  requireMatch,
  onConfirm,
}: Props) {
  const [typed, setTyped] = useState('');
  const canConfirm = requireMatch ? typed === requireMatch : true;

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) setTyped(''); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-overlay animate-fade-in" />
        <Dialog.Content
          className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-modal
                     w-[420px] bg-surface border border-border rounded-lg shadow-md p-6
                     animate-slide-up"
        >
          <Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title>
          {description && (
            <Dialog.Description className="mt-2 text-sm text-ink-muted">
              {description}
            </Dialog.Description>
          )}
          {requireMatch && (
            <div className="mt-4">
              <Input
                label={`확인하려면 "${requireMatch}" 를 입력하세요`}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                autoFocus
              />
            </div>
          )}
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="ghost">{cancelText}</Button>
            </Dialog.Close>
            <Button variant="destructive" disabled={!canConfirm} onClick={onConfirm}>
              {confirmText}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
