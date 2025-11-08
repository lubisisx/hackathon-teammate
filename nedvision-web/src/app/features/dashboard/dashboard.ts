import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClientModule } from '@angular/common/http';
import { ApiService } from '../../core/api.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, HttpClientModule],
  template: `
    <section class="p-4">
      <h2 class="text-2xl font-bold mb-3">Cashflow Forecast</h2>
      <div class="mb-4 flex gap-2">
        <input #b type="text" value="CPT02" class="border px-2 py-1" />
        <button (click)="load(b.value)" class="px-3 py-2 rounded bg-black text-white">Load Forecast</button>
      </div>
      <pre class="bg-gray-100 p-3 rounded max-h-96 overflow-auto">{{ preview | json }}</pre>
    </section>
  `,
})
export class DashboardComponent {
  private api = inject(ApiService);
  preview: any = null;

  load(branch: string) {
    this.api.getForecast(branch, 30).subscribe(res => {
      this.preview = res;
    });
  }
}
