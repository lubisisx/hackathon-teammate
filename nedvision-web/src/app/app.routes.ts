import { Routes } from '@angular/router';
import { DashboardShellComponent } from './features/dashboard/dashboard-shell';
import { WhatIfComponent } from './features/what-if/what-if';

export const routes: Routes = [
    { path: '', component: DashboardShellComponent },
    { path: 'what-if', component: WhatIfComponent }
];
