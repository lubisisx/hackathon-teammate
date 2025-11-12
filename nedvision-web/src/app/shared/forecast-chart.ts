import { Component, Input, OnChanges, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { BaseChartDirective } from 'ng2-charts';
import { ChartData, ChartOptions } from 'chart.js';
import 'chart.js/auto'; // auto-register controllers/elements for v4

export type Point = { date: string; cash: number };

// Mixed chart type alias so all generics line up
type MixedChart = 'bar' | 'line';

@Component({
  selector: 'app-forecast-chart',
  standalone: true,
  imports: [CommonModule, BaseChartDirective],
  template: `
    <div class="chart-wrap bg-white border rounded p-2">
      <canvas
        baseChart
        [data]="chartData"
        [options]="chartOptions"
        [type]="chartType">
      </canvas>
    </div>
  `,
  styles: [`
    .chart-wrap{ height:260px }
    @media (max-width: 992px){ .chart-wrap{ height:220px } }
  `]
})
export class ForecastChartComponent implements OnChanges {
  @Input() history: Point[] = [];
  @Input() forecast: Point[] = [];
  @Input() scenario: Point[] = [];

  @ViewChild(BaseChartDirective) chart?: BaseChartDirective;

  // ✅ use the same union everywhere
  chartType: MixedChart = 'bar';

  chartData: ChartData<MixedChart> = {
    labels: [],
    datasets: [
      { label: 'History', type: 'bar', data: [], backgroundColor: 'rgba(25,135,84,0.35)' },
      { label: 'Forecast', type: 'bar', data: [], backgroundColor: 'rgba(25,135,84,0.8)' },
      { label: 'What-if', type: 'line', data: [], borderColor: 'rgba(255,193,7,1)', backgroundColor: 'rgba(255,193,7,0.15)', borderWidth: 2, pointRadius: 0, tension: 0.2 }
    ]
  };

  chartOptions: ChartOptions<MixedChart> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: true, labels: { boxWidth: 16 } },
      tooltip: {
        callbacks: {
          label: (ctx) => `${ctx.dataset.label}: R ${Number(ctx.parsed.y ?? ctx.raw ?? 0).toLocaleString('en-ZA')}`
        }
      }
    },
    scales: {
      x: { ticks: { maxRotation: 0, autoSkip: true } },
      y: { ticks: { callback: (v) => 'R ' + Number(v).toLocaleString('en-ZA') } }
    }
  };

  ngOnChanges(): void {
    // same axis: last 10 history + full forecast
    const hist = (this.history || []).slice(-10);
    const fcs = this.forecast || [];
    const merged = [...hist, ...fcs];

    this.chartData.labels = merged.map(p => p.date);
    this.chartData.datasets[0].data = hist.map(p => p.cash);
    this.chartData.datasets[1].data = fcs.map(p => p.cash);

    const sMap = new Map((this.scenario || []).map(p => [p.date, p.cash]));
    this.chartData.datasets[2].data = (this.chartData.labels ?? []).map(d =>
      sMap.has(d as string) ? (sMap.get(d as string)! as number) : null
    );

    queueMicrotask(() => this.chart?.update());
  }
}
