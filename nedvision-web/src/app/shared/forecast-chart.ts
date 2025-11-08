import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

export type Point = { date: string; cash: number };

@Component({
  selector: 'app-forecast-chart',
  standalone: true,
  imports: [CommonModule],
  template: `
  <div class="chart" *ngIf="bars?.length">
    <div class="bar"
         *ngFor="let b of bars; trackBy:track"
         [title]="b.date + ' • ' + b.cash.toLocaleString('en-ZA',{style:'currency',currency:'ZAR'})"
         [style.height.%]="b.h"
         [style.opacity]="0.35"
         ></div>
  </div>
  `,
  styles: [`
    .chart{height:260px;display:flex;align-items:flex-end;gap:8px;padding:8px;border:1px solid var(--border);background:#fff;border-radius:8px}
    .bar{width:18px;background:var(--brand);border-radius:4px 4px 0 0;transition:height .2s ease}
    @media (max-width: 980px){ .bar{ width:10px; gap:4px } }
  `]
})
export class ForecastChartComponent {
  @Input() history: Point[] = [];
  @Input() forecast: Point[] = [];

  bars: { date: string, cash: number, h: number }[] = [];

  ngOnChanges() {
    const merged = [...this.history, ...this.forecast];
    if (!merged.length) { this.bars = []; return; }
    // Use only the last ~30 history points to keep it compact
    const lastHist = this.history.slice(-10);
    const data = [...lastHist, ...this.forecast];

    const vals = data.map(d => d.cash);
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = Math.max(1, max - min);
    this.bars = data.map(d => ({
      date: d.date,
      cash: d.cash,
      h: ((d.cash - min) / span) * 100
    }));
  }

  track = (_: number, item: any) => item.date;
}
