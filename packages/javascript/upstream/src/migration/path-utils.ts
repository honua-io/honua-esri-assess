/** Narrow URL/path helpers owned by the migration package. */
export function trimTrailingSlashes(value: string): string {
  let end = value.length;
  while (end > 0 && value.charCodeAt(end - 1) === 47) end -= 1;
  return end === value.length ? value : value.slice(0, end);
}

export function trimChar(value: string, char: string): string {
  const code = char.charCodeAt(0);
  let start = 0;
  let end = value.length;
  while (start < end && value.charCodeAt(start) === code) start += 1;
  while (end > start && value.charCodeAt(end - 1) === code) end -= 1;
  return start === 0 && end === value.length ? value : value.slice(start, end);
}

export function trimTrailingCharsIn(value: string, chars: string): string {
  const allowed = new Set(Array.from(chars, (char) => char.charCodeAt(0)));
  let end = value.length;
  while (end > 0 && allowed.has(value.charCodeAt(end - 1))) end -= 1;
  return end === value.length ? value : value.slice(0, end);
}

export function encodeServiceIdPath(serviceId: string): string {
  return serviceId
    .split("/")
    .filter((segment) => segment.length > 0)
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}
