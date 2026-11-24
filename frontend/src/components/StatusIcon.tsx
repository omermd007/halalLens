import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  RefreshCw,
  ShieldCheck,
  XOctagon,
} from 'lucide-react';
import { STATUS_META } from '../engine/rules';
import type { ProductEvaluation, StatusKey } from '../engine/types';

export function StatusGlyph({ status, size = 20 }: { status: StatusKey; size?: number }) {
  switch (status) {
    case 'certified_halal':
      return <ShieldCheck size={size} />;
    case 'verified_plant_or_microbial':
      return <CheckCircle2 size={size} />;
    case 'formulation_changed':
      return <RefreshCw size={size} />;
    case 'animal_or_haram':
      return <XOctagon size={size} />;
    default:
      return <AlertTriangle size={size} />;
  }
}

export function ProductRow({
  ev,
  meta,
  onOpen,
}: {
  ev: ProductEvaluation;
  meta?: string;
  onOpen: (id: string) => void;
}) {
  const st = STATUS_META[ev.status];
  const flaggedCount = ev.flags.filter((f) => f.res !== 'info').length;
  return (
    <button className={`prow tone-${st.tone}`} onClick={() => onOpen(ev.p.id)} type="button">
      <span className="prow-ic">
        <StatusGlyph status={ev.status} size={20} />
      </span>
      <span className="prow-main">
        <div className="prow-brand">{ev.p.brand}</div>
        <div className="prow-name">{ev.p.name}</div>
        <div className="prow-meta">
          {meta ?? (
            <>
              <span className="mono">{ev.p.upc}</span> · {flaggedCount} flagged
            </>
          )}
        </div>
      </span>
      <span className="pill">{st.short}</span>
      <ChevronRight size={18} className="chev" />
    </button>
  );
}
