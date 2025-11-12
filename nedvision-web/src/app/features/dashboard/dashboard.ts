import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClientModule } from '@angular/common/http';
import { ApiService } from '../../core/api.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, HttpClientModule],
  templateUrl: './dashboard.html'
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
