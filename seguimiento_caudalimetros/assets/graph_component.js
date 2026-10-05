export default function({ data, parentElement }) {
  const shell = parentElement.querySelector(".graph-shell");
  const frame = parentElement.querySelector(".graph-frame");
  const stack = parentElement.querySelector(".plotly-stack");
  const height = Math.max(360, Math.min(Number(data?.height || 640), 1000));
  let disposed = false;

  shell.style.minHeight = `${height}px`;

  if (data?.mode === "plotly") {
    frame.hidden = true;
    frame.removeAttribute("srcdoc");
    stack.hidden = false;
    stack.replaceChildren();

    const figures = Array.isArray(data?.figures) ? data.figures : [];
    const perFigureHeight =
      figures.length > 1 ? Math.max(360, Math.floor(height / figures.length)) : height;

    for (const figure of figures) {
      const target = document.createElement("div");
      target.className = "plotly-figure";
      target.style.height = `${perFigureHeight}px`;
      stack.appendChild(target);

      const layout = { ...(figure?.layout || {}) };
      delete layout.width;
      delete layout.height;
      layout.autosize = true;

      const config = {
        responsive: true,
        displaylogo: false,
        ...(figure?.config || {}),
      };

      Promise.resolve(
        globalThis.Plotly.react(
          target,
          Array.isArray(figure?.data) ? figure.data : [],
          layout,
          config,
        ),
      ).catch((error) => {
        if (!disposed) {
          target.innerHTML =
            '<p style="font-family:sans-serif;padding:1rem">No fue posible renderizar el gráfico Plotly.</p>';
          console.error(error);
        }
      });
    }
  } else {
    stack.hidden = true;
    stack.replaceChildren();
    frame.hidden = false;
    frame.style.height = `${height}px`;
    frame.setAttribute("sandbox", "allow-scripts allow-downloads");
    frame.setAttribute("referrerpolicy", "no-referrer");
    frame.srcdoc =
      data?.html ||
      '<p style="font-family:sans-serif;padding:1rem">Sin gráfico disponible.</p>';
  }

  return () => {
    disposed = true;
    frame.removeAttribute("srcdoc");
    for (const target of stack.querySelectorAll(".plotly-figure")) {
      try {
        globalThis.Plotly?.purge(target);
      } catch (_) {
        // No-op.
      }
    }
    stack.replaceChildren();
  };
}
