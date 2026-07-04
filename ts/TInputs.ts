export type TPoint2D = [x: number, y: number];

export type TBBox = [
  x: number,
  y: number,
  width: number,
  height: number,
];

export type TLabColor = [l: number, a: number, b: number];

export type THold = {
  id: number;
  polygon: TPoint2D[];
  bbox: TBBox;
  center: TPoint2D;
  color_hex: `#${string}`;
  color_lab: TLabColor;
  neighbors: number[];
};

export type TInputs = {
  image: string;
  image_size: [width: number, height: number];
  holds: THold[];
  tags: string[];
  routes_hint: {
    count: number;
  };
};
