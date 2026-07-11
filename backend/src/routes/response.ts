export function ok<T>(data: T) {
  return { success: true, data, error: null };
}

export function fail(code: string, message: string, status = 400) {
  return { status, body: { success: false, data: null, error: { code, message } } };
}
