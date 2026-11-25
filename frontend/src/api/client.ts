import type {
  BrandPolicy,
  BrandPolicyCreateRequest,
  CommunityNote,
  ForumParsePostRequest,
  ForumParsePostResponse,
  ForumScanRequest,
  ForumScanResponse,
  HealthResponse,
  IngredientRule,
  NoteCreateRequest,
  OcrAnalyzeRequest,
  OcrAnalyzeResponse,
  OutreachDraftRequest,
  OutreachDraftResponse,
  OutreachInquiry,
  OutreachState,
  ProductCreateRequest,
  ProductDetail,
  ProductSummary,
  ReviewQueueResponse,
  ScanResponse,
  SnapshotCreateRequest,
  SnapshotCreateResponse,
  StrictnessProfile,
  VerificationCreateRequest,
} from '../types';

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let passcode = '';
  try {
    passcode = sessionStorage.getItem('halallens.passcode') || '';
  } catch {
    // ignore storage errors
  }

  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(passcode ? { 'X-Passcode': passcode } : {}),
    ...(init?.headers as Record<string, string> | undefined),
  };

  if (init?.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers,
    });
  } catch {
    throw new ApiError(
      0,
      'Unable to reach the HalalLens API server. Confirm the backend is running on port 8000.'
    );
  }

  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    if (isJson) {
      try {
        const errBody = await response.json();
        if (typeof errBody?.detail === 'string') {
          detail = errBody.detail;
        } else if (Array.isArray(errBody?.detail)) {
          detail = errBody.detail
            .map((item: { loc?: string[]; msg?: string }) =>
              item.loc ? `${item.loc.slice(-1)[0]}: ${item.msg}` : item.msg
            )
            .join('; ');
        } else if (typeof errBody?.message === 'string') {
          detail = errBody.message;
        }
      } catch {
        // fallback to status message
      }
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const api = {
  getHealth(): Promise<HealthResponse> {
    return apiRequest<HealthResponse>('/api/health');
  },

  listProducts(params?: { q?: string; status?: string }): Promise<{ products: ProductSummary[] }> {
    const search = new URLSearchParams();
    if (params?.q && params.q.trim()) {
      search.set('q', params.q.trim());
    }
    if (params?.status && params.status !== 'all') {
      search.set('status', params.status);
    }
    const qs = search.toString();
    return apiRequest<{ products: ProductSummary[] }>(`/api/products${qs ? `?${qs}` : ''}`);
  },

  getProduct(productId: string): Promise<ProductDetail> {
    return apiRequest<ProductDetail>(`/api/products/${encodeURIComponent(productId)}`);
  },

  createProduct(payload: ProductCreateRequest): Promise<ProductDetail> {
    return apiRequest<ProductDetail>('/api/products', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  scanUpc(upc: string, allowExternal: boolean): Promise<ScanResponse> {
    return apiRequest<ScanResponse>('/api/scan', {
      method: 'POST',
      body: JSON.stringify({ upc: upc.trim(), allow_external: allowExternal }),
    });
  },

  createSnapshot(
    productId: string,
    payload: SnapshotCreateRequest
  ): Promise<SnapshotCreateResponse> {
    return apiRequest<SnapshotCreateResponse>(
      `/api/products/${encodeURIComponent(productId)}/snapshots`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    );
  },

  addNote(productId: string, payload: NoteCreateRequest): Promise<CommunityNote> {
    return apiRequest<CommunityNote>(
      `/api/products/${encodeURIComponent(productId)}/notes`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    );
  },

  analyzeOcr(payload: OcrAnalyzeRequest): Promise<OcrAnalyzeResponse> {
    return apiRequest<OcrAnalyzeResponse>('/api/ocr/analyze', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  createVerification(payload: VerificationCreateRequest): Promise<ProductDetail> {
    return apiRequest<ProductDetail>('/api/verifications', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  draftOutreach(payload: OutreachDraftRequest): Promise<OutreachDraftResponse> {
    return apiRequest<OutreachDraftResponse>('/api/outreach/draft', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  updateOutreachState(inquiryId: string, state: OutreachState): Promise<OutreachInquiry> {
    return apiRequest<OutreachInquiry>(`/api/outreach/${encodeURIComponent(inquiryId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ state }),
    });
  },

  scanForums(productId: string, payload?: ForumScanRequest): Promise<ForumScanResponse> {
    return apiRequest<ForumScanResponse>(
      `/api/forums/scan/${encodeURIComponent(productId)}`,
      {
        method: 'POST',
        body: JSON.stringify(payload ?? { include_live_reddit: true }),
      }
    );
  },

  parseForumPost(payload: ForumParsePostRequest): Promise<ForumParsePostResponse> {
    return apiRequest<ForumParsePostResponse>('/api/forums/parse-post', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  getReviewQueue(): Promise<ReviewQueueResponse> {
    return apiRequest<ReviewQueueResponse>('/api/review-queue');
  },

  listIngredients(q?: string): Promise<{ rules: IngredientRule[] }> {
    const qs = q && q.trim() ? `?q=${encodeURIComponent(q.trim())}` : '';
    return apiRequest<{ rules: IngredientRule[] }>(`/api/ingredients${qs}`);
  },

  listBrandPolicies(): Promise<{ policies: BrandPolicy[] }> {
    return apiRequest<{ policies: BrandPolicy[] }>('/api/brand-policies');
  },

  createBrandPolicy(payload: BrandPolicyCreateRequest): Promise<BrandPolicy> {
    return apiRequest<BrandPolicy>('/api/brand-policies', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  getStrictnessProfile(): Promise<StrictnessProfile> {
    return apiRequest<StrictnessProfile>('/api/settings/profile');
  },

  updateStrictnessProfile(profile: StrictnessProfile): Promise<StrictnessProfile> {
    return apiRequest<StrictnessProfile>('/api/settings/profile', {
      method: 'PUT',
      body: JSON.stringify(profile),
    });
  },

  lookupBrandContact(brand: string): Promise<{
    brand: string;
    matched_query: string;
    source: 'verified_directory' | 'web_lookup' | 'not_found';
    verified: boolean;
    contact_type: 'email' | 'web_form' | 'unknown';
    email: string | null;
    contact_url: string | null;
    phone: string | null;
    search_url: string;
    note: string | null;
  }> {
    return apiRequest(`/api/brands/lookup-contact?brand=${encodeURIComponent(brand.trim())}`);
  },
};
