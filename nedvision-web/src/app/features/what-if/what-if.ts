import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClientModule } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ApiService, Adjustment } from '../../core/api.service';

@Component({
  selector: 'app-what-if',
  standalone: true,
  imports: [CommonModule, HttpClientModule, FormsModule],
  template: `
    <section class="p-4">
      <h2 class="text-2xl font-bold mb-3">What-if Simulation</h2>

      <div class="flex flex-col gap-2 mb-3 max-w-md">
        <label class="flex justify-between">
          <span>Date</span>
          <input type="date" [(ngModel)]="date" class="border px-2 py-1" />
        </label>
        <label class="flex justify-between">
          <span>Delta (ZAR, negative for outflow)</span>
          <input type="number" [(ngModel)]="delta" class="border px-2 py-1" />
        </label>
        <label class="flex justify-between">
          <span>Branch</span>
          <input type="text" [(ngModel)]="branch" class="border px-2 py-1" />
        </label>
        <div class="flex gap-2">
          <button (click)="simulate()" class="px-3 py-2 rounded bg-black text-white">Simulate</button>
          <button (click)="presetSalaries()" class="px-3 py-2 rounded border">Preset: Salaries Early</button>
          <button (click)="presetInvoice()" class="px-3 py-2 rounded border">Preset: Invoice Late</button>
        </div>
      </div>

      <pre class="bg-gray-100 p-3 rounded max-h-96 overflow-auto">{{ result | json }}</pre>
    </section>
  `,
})
export class WhatIfComponent {
  private api = inject(ApiService);
  date = '';
  delta = 0;
  branch = 'CPT02';
  result: any = null;

  simulate() {
    const adjustments: Adjustment[] = [{ date: this.date, delta: this.delta, label: 'Manual' }];
    this.api.simulate(this.branch, adjustments, 30).subscribe(res => this.result = res);
  }

  presetSalaries() {
    // Example: move salaries earlier by 250,000 ZAR
    this.date = new Date().toISOString().slice(0, 10);
    this.delta = -250000;
    this.simulate();
  }

  presetInvoice() {
    // Example: delay invoice inflow 180,000 ZAR to 3 days from now
    const d = new Date(); d.setDate(d.getDate() + 3);
    this.date = d.toISOString().slice(0, 10);
    this.delta = 180000;
    this.simulate();
  }
}
