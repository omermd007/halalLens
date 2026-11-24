import { queueOf } from '../engine/evaluator';
import type { ProductEvaluation } from '../engine/types';
import { ProductRow } from './StatusIcon';

export function TodoView({
  evals,
  onOpenProduct,
}: {
  evals: ProductEvaluation[];
  onOpenProduct: (id: string) => void;
}) {
  const q = queueOf(evals);

  const sections: Array<{
    eyebrow: string;
    title: string;
    desc: string;
    items: ProductEvaluation[];
  }> = [
    {
      eyebrow: 'Urgent',
      title: 'Recipe changed',
      desc: 'Ingredients changed since you confirmed these. Re-check with the brand.',
      items: q.changed,
    },
    {
      eyebrow: 'To verify',
      title: 'Doubtful — needs confirmation',
      desc: 'Open an item to draft an email or log a brand reply.',
      items: q.check,
    },
    {
      eyebrow: 'In progress',
      title: 'Waiting on a brand reply',
      desc: 'Items with a drafted or sent email.',
      items: q.waiting,
    },
    {
      eyebrow: 'Maintenance',
      title: 'Confirmations expiring within 30 days',
      desc: 'Annual re-check to catch silent supplier switches.',
      items: q.expiring,
    },
  ];

  return (
    <div className="stack fadein">
      <div>
        <h1 className="page-title">To-do</h1>
        <p className="page-sub">
          Products that need a quick check, an email to the brand, or a re-check after a recipe change.
        </p>
      </div>

      <div className="stats">
        <div className="stat tone-changed">
          <div className="stat-n">{q.changed.length}</div>
          <div className="stat-l">Recipe changed</div>
        </div>
        <div className="stat tone-doubt">
          <div className="stat-n">{q.check.length}</div>
          <div className="stat-l">Needs check</div>
        </div>
        <div className="stat">
          <div className="stat-n">{q.waiting.length}</div>
          <div className="stat-l">Waiting on reply</div>
        </div>
        <div className="stat tone-ok">
          <div className="stat-n">{q.expiring.length}</div>
          <div className="stat-l">Expiring soon</div>
        </div>
      </div>

      {sections.map((sec) => (
        <section className="card" key={sec.title}>
          <div className="card-head">
            <div>
              <div className="eyebrow">{sec.eyebrow}</div>
              <div className="title">{sec.title}</div>
              <div className="small muted">{sec.desc}</div>
            </div>
          </div>
          <div className="plist">
            {sec.items.length ? (
              sec.items.map((ev) => (
                <ProductRow key={ev.p.id} ev={ev} meta={ev.summary} onOpen={onOpenProduct} />
              ))
            ) : (
              <div className="empty small">Nothing here — all clear.</div>
            )}
          </div>
        </section>
      ))}
    </div>
  );
}
