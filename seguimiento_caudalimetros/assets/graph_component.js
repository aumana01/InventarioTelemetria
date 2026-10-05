export default function({ data, parentElement }) {
  const shell = parentElement.querySelector(".graph-shell");
  const frame = parentElement.querySelector(".graph-frame");
  const height = Math.max(360, Math.min(Number(data?.height || 640), 1000));
  shell.style.minHeight = `${height}px`;
  frame.style.height = `${height}px`;
  frame.setAttribute("sandbox", "allow-scripts allow-downloads");
  frame.setAttribute("referrerpolicy", "no-referrer");
  frame.srcdoc =
    data?.html ||
    '<p style="font-family:sans-serif;padding:1rem">Sin gráfico disponible.</p>';

  return () => {
    frame.removeAttribute("srcdoc");
  };
}
