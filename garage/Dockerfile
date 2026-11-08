# The Garage image has no shell, so the bootstrap runs the same `garage`
# binary from Alpine.
FROM dxflrs/garage:v2.5.0 AS garage

FROM alpine:3.22
COPY --from=garage /garage /usr/local/bin/garage
COPY garage.toml /etc/garage.toml
COPY init.sh /usr/local/bin/garage-init
ENTRYPOINT ["/usr/local/bin/garage-init"]
