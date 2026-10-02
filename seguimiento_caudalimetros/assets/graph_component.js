export default function({ data, parentElement }) {
  const frame = parentElement.querySelector(".graph-frame");
  frame.setAttribute("sandbox", "allow-scripts allow-downloads");
  frame.setAttribute("referrerpolicy", "no-referrer");
  frame.srcdoc =
    data?.html ||
    '<p style="font-family:sans-serif;padding:1rem">Sin gráfico disponible.</p>';

  return () => {
    frame.removeAttribute("srcdoc");
  };
}
