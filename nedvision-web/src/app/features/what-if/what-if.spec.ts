import { ComponentFixture, TestBed } from '@angular/core/testing';

import { WhatIf } from './what-if';

describe('WhatIf', () => {
  let component: WhatIf;
  let fixture: ComponentFixture<WhatIf>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [WhatIf]
    })
    .compileComponents();

    fixture = TestBed.createComponent(WhatIf);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
