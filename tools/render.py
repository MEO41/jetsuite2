"""Off-screen VTK render of the cached CAD parts: full view and a meridional half-section."""
import sys, json
from pathlib import Path
sys.path.insert(0, "src")
import cadquery as cq
from jetsuite2.cad import cadlib
from jetsuite2.cad.parts import COLORS
import vtk

cad = Path(sys.argv[1]) / "cad"
man = json.loads((cad / "manifest.json").read_text())
shapes = {}
for b, e in man["builders"].items():
    for p, f in e["files"].items():
        shapes[p] = (cadlib.import_brep(cad / "cache" / f), e["materials"][p])

def render(out, section):
    ren = vtk.vtkRenderer(); ren.SetBackground(1, 1, 1)
    half = cq.Workplane("XY").box(2000, 2000, 2000, centered=(True, True, False)).translate((0, 0, 0)).val()  # z >= 0
    for name, (shp, mat) in shapes.items():
        s = shp
        if section:
            try:
                s = shp.cut(half)
            except Exception:
                pass
        try:
            pd = s.toVtkPolyData(tolerance=0.2, angularTolerance=0.2)
        except Exception:
            continue
        m = vtk.vtkPolyDataMapper(); m.SetInputData(pd)
        a = vtk.vtkActor(); a.SetMapper(m)
        c = COLORS.get(mat, (0.6, 0.6, 0.6)); a.GetProperty().SetColor(*c)
        ren.AddActor(a)
    win = vtk.vtkRenderWindow(); win.SetOffScreenRendering(1); win.AddRenderer(ren); win.SetSize(1600, 900)
    cam = ren.GetActiveCamera()
    if section:
        cam.SetPosition(180, 0, 900); cam.SetFocalPoint(180, 0, 0); cam.SetViewUp(0, 1, 0)
    else:
        cam.SetPosition(-300, 250, 500); cam.SetFocalPoint(180, 0, 0); cam.SetViewUp(0, 1, 0)
    ren.ResetCamera(); cam.Zoom(1.4 if section else 1.2)
    win.Render()
    w2i = vtk.vtkWindowToImageFilter(); w2i.SetInput(win); w2i.Update()
    wr = vtk.vtkPNGWriter(); wr.SetFileName(out); wr.SetInputConnection(w2i.GetOutputPort()); wr.Write()
    print("wrote", out)

render(sys.argv[2], section=False)
render(sys.argv[3], section=True)
