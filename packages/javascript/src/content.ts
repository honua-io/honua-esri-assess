/** Conservative local WebMap URL rewrite; remote portal operations remain SDK-dependent. */
export function rewriteWebMapUrls(input: unknown, sourcePrefix: string, targetPrefix: string): unknown {
  const text = JSON.stringify(input);
  return JSON.parse(text.split(sourcePrefix).join(targetPrefix)) as unknown;
}
