import { NextRequest, NextResponse } from "next/server";

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

type RouteContext = {
  params: Promise<{
    path?: string[];
  }>;
};

export const runtime = "nodejs";

export async function GET(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}

async function proxyRequest(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const params = await context.params;
  const target = backendUrl(params.path ?? [], request.nextUrl.search);
  const headers = forwardedHeaders(request);
  const init: RequestInit = {
    method: request.method,
    headers,
    cache: "no-store"
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  try {
    const response = await fetch(target, init);
    const responseHeaders = new Headers(response.headers);
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("content-length");

    return new NextResponse(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders
    });
  } catch {
    return NextResponse.json(
      {
        detail:
          "Backend is unreachable. Start FastAPI on 127.0.0.1:8000 or set API_BASE_URL/NEXT_PUBLIC_API_BASE_URL."
      },
      { status: 502 }
    );
  }
}

function backendUrl(pathParts: string[], search: string): string {
  const baseUrl = (process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_BACKEND_URL).replace(
    /\/$/,
    ""
  );
  const path = pathParts.map(encodeURIComponent).join("/");
  return `${baseUrl}/${path}${search}`;
}

function forwardedHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const apiKey = request.headers.get("x-api-key");

  if (contentType) {
    headers.set("content-type", contentType);
  }
  if (apiKey) {
    headers.set("x-api-key", apiKey);
  }

  return headers;
}
