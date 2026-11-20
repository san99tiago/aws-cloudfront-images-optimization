import type { Delivery } from "../lib/deviceCache";
import { ROUTE_NODES, routeStart } from "../lib/deliveryView";

interface Props {
  delivery: Delivery;
  pop?: string;
  size?: "small" | "large";
}

/** S3 -> Origin Shield -> REC -> POP -> device, lit from the first layer that held the bytes. */
export function RouteStrip({ delivery, pop, size = "small" }: Props) {
  const start = routeStart(delivery);
  return (
    <ol className={`route route--${size} route--${delivery.source}`} aria-label="Ruta de la imagen">
      {ROUTE_NODES.map((node, index) => {
        const lit = index >= start;
        const label = node === "POP" && pop ? pop.split("-")[0] : node;
        return (
          <li key={node} className={`route__node${lit ? " is-lit" : ""}${index === start ? " is-start" : ""}`}>
            <span className="route__dot" aria-hidden="true" />
            <span className="route__label">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}
